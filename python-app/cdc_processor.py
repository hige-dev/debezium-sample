#!/usr/bin/env python3
import json
import logging
import os
import time
from typing import Dict, Any
from kafka import KafkaConsumer
import psycopg2
from psycopg2.extras import DictCursor
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CDCProcessor:
    def __init__(self):
        self.kafka_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:29092')
        self.postgres_config = {
            'host': os.getenv('POSTGRES_HOST', 'postgres'),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
            'database': os.getenv('POSTGRES_DB', 'testdb'),
            'user': os.getenv('POSTGRES_USER', 'postgres'),
            'password': os.getenv('POSTGRES_PASSWORD', 'postgres')
        }
        self.consumer = None
        self.db_connection = None

    def wait_for_services(self):
        logger.info("Waiting for services to be ready...")

        # Wait for Kafka
        while True:
            try:
                consumer = KafkaConsumer(
                    bootstrap_servers=[self.kafka_servers],
                    consumer_timeout_ms=1000
                )
                consumer.close()
                logger.info("Kafka is ready")
                break
            except Exception as e:
                logger.info(f"Waiting for Kafka: {e}")
                time.sleep(5)

        # Wait for PostgreSQL
        while True:
            try:
                conn = psycopg2.connect(**self.postgres_config)
                conn.close()
                logger.info("PostgreSQL is ready")
                break
            except Exception as e:
                logger.info(f"Waiting for PostgreSQL: {e}")
                time.sleep(5)

        # Wait for Debezium Connect
        while True:
            try:
                response = requests.get('http://connect:8083/connectors')
                if response.status_code == 200:
                    logger.info("Debezium Connect is ready")
                    break
            except Exception as e:
                logger.info(f"Waiting for Debezium Connect: {e}")
                time.sleep(5)

        # Setup Debezium connector
        self.setup_debezium_connector()

    def setup_debezium_connector(self):
        logger.info("Setting up Debezium connector...")

        connector_config = {
            "name": "postgres-connector",
            "config": {
                "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
                "tasks.max": "1",
                "database.hostname": "postgres",
                "database.port": "5432",
                "database.user": "postgres",
                "database.password": "postgres",
                "database.dbname": "testdb",
                "database.server.name": "dbserver1",
                "table.include.list": "public.tablea",
                "topic.prefix": "dbserver1",
                "plugin.name": "pgoutput",
                "slot.name": "debezium",
                "publication.name": "dbz_publication",
                "publication.autocreate.mode": "filtered",
                "schema.history.internal.kafka.bootstrap.servers": "kafka:29092",
                "schema.history.internal.kafka.topic": "schema-changes.testdb",
                "transforms": "route",
                "transforms.route.type": "org.apache.kafka.connect.transforms.RegexRouter",
                "transforms.route.regex": "([^.]+)\\.([^.]+)\\.([^.]+)",
                "transforms.route.replacement": "cdc.$3"
            }
        }

        try:
            # Check if connector already exists
            response = requests.get('http://connect:8083/connectors/postgres-connector')
            if response.status_code == 200:
                logger.info("Connector already exists")
                return

            # Create connector
            response = requests.post(
                'http://connect:8083/connectors',
                headers={'Content-Type': 'application/json'},
                json=connector_config
            )

            if response.status_code in [201, 409]:
                logger.info("Debezium connector created successfully")
            else:
                logger.error(f"Failed to create connector: {response.text}")

        except Exception as e:
            logger.error(f"Error setting up connector: {e}")

    def connect_to_postgres(self):
        try:
            self.db_connection = psycopg2.connect(**self.postgres_config)
            self.db_connection.autocommit = True
            logger.info("Connected to PostgreSQL")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    def process_change_event(self, message: Dict[str, Any]):
        """Process a CDC change event and transform data for tableB"""
        try:
            payload = message.get('payload', {})
            op = payload.get('op')  # c=create, u=update, d=delete

            if op == 'c':  # INSERT
                after = payload.get('after', {})
                self.insert_to_tableb(after)
            elif op == 'u':  # UPDATE
                after = payload.get('after', {})
                before = payload.get('before', {})
                self.update_tableb(before, after)
            elif op == 'd':  # DELETE
                before = payload.get('before', {})
                self.delete_from_tableb(before)

        except Exception as e:
            logger.error(f"Error processing change event: {e}")

    def insert_to_tableb(self, data: Dict[str, Any]):
        """Transform and insert data into tableB"""
        try:
            # データ変換例: 名前を大文字に変換し、プレフィックスを追加
            transformed_data = {
                'id': data.get('id'),
                'name': f"PROCESSED_{data.get('name', '').upper()}",
                'email': data.get('email'),
                'age': data.get('age', 0) + 1,  # 年齢を+1する例
                'processed_at': 'NOW()'
            }

            cursor = self.db_connection.cursor()
            insert_query = """
                INSERT INTO tableb (id, name, email, age, processed_at)
                VALUES (%(id)s, %(name)s, %(email)s, %(age)s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    age = EXCLUDED.age,
                    processed_at = NOW()
            """
            cursor.execute(insert_query, transformed_data)
            logger.info(f"Inserted/Updated record in tableB: {transformed_data}")

        except Exception as e:
            logger.error(f"Error inserting to tableB: {e}")

    def update_tableb(self, before_data: Dict[str, Any], after_data: Dict[str, Any]):
        """Handle update events"""
        # 更新の場合は新しいデータでinsert_to_tablebを呼ぶ
        self.insert_to_tableb(after_data)

    def delete_from_tableb(self, data: Dict[str, Any]):
        """Handle delete events"""
        try:
            cursor = self.db_connection.cursor()
            delete_query = "DELETE FROM tableb WHERE id = %s"
            cursor.execute(delete_query, (data.get('id'),))
            logger.info(f"Deleted record from tableB with id: {data.get('id')}")

        except Exception as e:
            logger.error(f"Error deleting from tableB: {e}")

    def run(self):
        logger.info("Starting CDC Processor...")

        self.wait_for_services()
        self.connect_to_postgres()

        # Kafka Consumer setup
        self.consumer = KafkaConsumer(
            'cdc.tablea',  # Topic name from Debezium transform
            bootstrap_servers=[self.kafka_servers],
            value_deserializer=lambda x: json.loads(x.decode('utf-8')) if x else None,
            auto_offset_reset='earliest',
            group_id='cdc-processor-group'
        )

        logger.info("Listening for CDC events...")

        try:
            for message in self.consumer:
                if message.value:
                    logger.info(f"Received CDC event: {message.value}")
                    self.process_change_event(message.value)

        except KeyboardInterrupt:
            logger.info("Shutting down CDC processor...")
        except Exception as e:
            logger.error(f"Error in CDC processor: {e}")
        finally:
            if self.consumer:
                self.consumer.close()
            if self.db_connection:
                self.db_connection.close()

if __name__ == "__main__":
    processor = CDCProcessor()
    processor.run()