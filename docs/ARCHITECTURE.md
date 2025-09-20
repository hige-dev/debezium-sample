# Debezium CDC System - アーキテクチャ詳細

## システムアーキテクチャ概要

### 全体構成図

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                  Docker Compose Environment                              │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐                     │
│  │   PostgreSQL    │    │    Zookeeper     │    │     Kafka       │                     │
│  │   Container     │    │    Container     │    │   Container     │                     │
│  │                 │    │                  │    │                 │                     │
│  │ ┌─────────────┐ │    │ Port: 2181       │    │ Ports:          │                     │
│  │ │   tableA    │ │    │                  │    │ - 9092 (API)    │                     │
│  │ │ (source)    │ │    │ Manages Kafka    │    │ - 9101 (JMX)    │                     │
│  │ │             │ │    │ cluster metadata │    │                 │                     │
│  │ └─────────────┘ │    │                  │    │ Topics:         │                     │
│  │ ┌─────────────┐ │    └──────────────────┘    │ - cdc.tablea    │                     │
│  │ │   tableB    │ │                            │ - schema-changes │                     │
│  │ │ (target)    │ │    ┌──────────────────┐    │ - connect-*     │                     │
│  │ │             │ │    │ Debezium Connect │    │                 │                     │
│  │ └─────────────┘ │    │    Container     │    └─────────────────┘                     │
│  │                 │    │                  │                                            │
│  │ Port: 5432      │    │ Port: 8083       │    ┌─────────────────┐                     │
│  │ WAL: logical    │    │                  │    │ Python CDC      │                     │
│  │                 │    │ Connectors:      │    │   Processor     │                     │
│  └─────────────────┘    │ - postgres-conn  │    │   Container     │                     │
│           │              │                  │    │                 │                     │
│           │              └──────────────────┘    │ ┌─────────────┐ │                     │
│           │                       │              │ │cdc_processor│ │                     │
│           │                       │              │ │   .py       │ │                     │
│           │                       │              │ │             │ │                     │
│           │                       │              │ └─────────────┘ │                     │
│           │                       │              │                 │                     │
│           │                       │              └─────────────────┘                     │
│           │                       │                       │                              │
│           └───────────────────────┼───────────────────────┘                              │
│                                   │                                                      │
└───────────────────────────────────┼──────────────────────────────────────────────────────┘
                                    │
                           ┌────────▼────────┐
                           │  Data Flow      │
                           │  Processing     │
                           └─────────────────┘
```

## データフロー詳細図

```
PostgreSQL WAL → Debezium → Kafka Topic → Python Processor → PostgreSQL tableB

┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│             │ ①   │             │ ②   │             │ ③   │             │ ④   │             │
│   tableA    │────▶│  Debezium   │────▶│   Kafka     │────▶│   Python    │────▶│   tableB    │
│             │     │  Connector  │     │   Topic     │     │ Processor   │     │             │
│             │     │             │     │             │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘

① WAL Streaming          ② CDC Event Publish    ③ Message Consume     ④ Transformed Insert
   - INSERT/UPDATE/DELETE   - JSON format          - Kafka Consumer       - Business Logic
   - Binary Log Parsing     - Schema metadata      - Offset management    - Data Transformation
   - Real-time capture      - Transactional        - Error handling       - UPSERT operations
```

## コンポーネント詳細

### 1. PostgreSQL Database Server

```yaml
Service Configuration:
  Image: postgres:15
  Ports: 5432:5432
  Volumes:
    - postgres_data:/var/lib/postgresql/data
    - postgresql.conf:/etc/postgresql/postgresql.conf
    - init.sql:/docker-entrypoint-initdb.d/init.sql

Key Settings:
  wal_level: logical
  max_wal_senders: 10
  max_replication_slots: 10

Database Objects:
  - Database: testdb
  - Tables: tablea (source), tableb (target)
  - Replication Slot: debezium
  - Publication: dbz_publication
```

#### テーブル構造

**tableA (Source Table)**
```sql
CREATE TABLE public.tablea (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE,
    age INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**tableB (Target Table)**
```sql
CREATE TABLE public.tableb (
    id INTEGER PRIMARY KEY,
    name VARCHAR(200),
    email VARCHAR(255),
    age INTEGER,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_table VARCHAR(50) DEFAULT 'tablea'
);
```

### 2. Apache Zookeeper

```yaml
Service Configuration:
  Image: confluentinc/cp-zookeeper:7.4.0
  Ports: 2181:2181

Environment Variables:
  ZOOKEEPER_CLIENT_PORT: 2181
  ZOOKEEPER_TICK_TIME: 2000

Responsibilities:
  - Kafka broker coordination
  - Topic metadata management
  - Consumer group coordination
  - Configuration management
```

### 3. Apache Kafka

```yaml
Service Configuration:
  Image: confluentinc/cp-kafka:7.4.0
  Ports:
    - 9092:9092 (Client API)
    - 9101:9101 (JMX Metrics)

Key Configuration:
  KAFKA_BROKER_ID: 1
  KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
  KAFKA_ADVERTISED_LISTENERS:
    - PLAINTEXT://kafka:29092 (Internal)
    - PLAINTEXT_HOST://localhost:9092 (External)

Topics Created:
  - cdc.tablea: CDC events from tableA
  - schema-changes.testdb: Schema evolution events
  - connect-configs: Kafka Connect configurations
  - connect-offsets: Offset storage
  - connect-status: Connector status
```

#### Kafkaトピック設定

```bash
Topic: cdc.tablea
├── Partitions: 1 (default)
├── Replication Factor: 1
├── Retention: 168 hours (7 days)
└── Message Format: JSON (Debezium format)

Message Structure:
{
  "schema": { ... },
  "payload": {
    "before": { ... },      // Previous state (UPDATE/DELETE)
    "after": { ... },       // New state (INSERT/UPDATE)
    "op": "c|u|d|r",       // Operation type
    "source": { ... },      // Metadata
    "ts_ms": 1234567890     // Timestamp
  }
}
```

### 4. Debezium Connect Platform

```yaml
Service Configuration:
  Image: debezium/connect:2.4
  Ports: 8083:8083

Environment Variables:
  BOOTSTRAP_SERVERS: kafka:29092
  GROUP_ID: 1
  CONFIG_STORAGE_TOPIC: my_connect_configs
  OFFSET_STORAGE_TOPIC: my_connect_offsets
  STATUS_STORAGE_TOPIC: my_connect_statuses

REST API Endpoints:
  GET /connectors: List all connectors
  POST /connectors: Create new connector
  GET /connectors/{name}/status: Connector status
  DELETE /connectors/{name}: Delete connector
```

#### PostgreSQL Connector設定

```json
{
  "name": "postgres-connector",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
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
    "transforms": "route",
    "transforms.route.type": "org.apache.kafka.connect.transforms.RegexRouter",
    "transforms.route.regex": "([^.]+)\\.([^.]+)\\.([^.]+)",
    "transforms.route.replacement": "cdc.$3"
  }
}
```

### 5. Python CDC Processor

```yaml
Service Configuration:
  Build: Dockerfile.python
  Working Directory: /app

Dependencies (requirements.txt):
  - kafka-python==2.0.2
  - psycopg2-binary==2.9.9
  - confluent-kafka==2.3.0
  - requests==2.31.0
  - json-logging==1.3.0

Environment Variables:
  KAFKA_BOOTSTRAP_SERVERS: kafka:29092
  POSTGRES_HOST: postgres
  POSTGRES_PORT: 5432
  POSTGRES_DB: testdb
  POSTGRES_USER: postgres
  POSTGRES_PASSWORD: postgres
```

#### Python処理アーキテクチャ

```python
class CDCProcessor:
    ├── __init__(): 設定初期化
    ├── wait_for_services(): サービス待機
    ├── setup_debezium_connector(): コネクタ設定
    ├── connect_to_postgres(): DB接続
    ├── process_change_event(): イベント処理
    ├── insert_to_tableb(): INSERT処理
    ├── update_tableb(): UPDATE処理
    ├── delete_from_tableb(): DELETE処理
    └── run(): メインループ

Processing Flow:
1. Kafka Consumer初期化
2. CDC イベント受信
3. ペイロード解析
4. データ変換適用
5. PostgreSQL操作実行
6. エラーハンドリング
7. オフセットコミット
```

## ネットワーク通信

### 内部通信（Docker Network）

```
Network: debezium-network (bridge)

Communication Paths:
┌─────────────┐ 5432 ┌─────────────┐
│ Debezium    │─────▶│ PostgreSQL  │
│ Connect     │      │             │
└─────────────┘      └─────────────┘
       │
       │ 29092
       ▼
┌─────────────┐      ┌─────────────┐
│   Kafka     │ 2181 │ Zookeeper   │
│             │◀─────│             │
└─────────────┘      └─────────────┘
       │
       │ 29092
       ▼
┌─────────────┐ 5432 ┌─────────────┐
│ Python CDC  │─────▶│ PostgreSQL  │
│ Processor   │      │             │
└─────────────┘      └─────────────┘
```

### 外部アクセス（Host Ports）

```
External Port Mapping:
- 5432:5432   → PostgreSQL (Database Access)
- 9092:9092   → Kafka (Producer/Consumer API)
- 9101:9101   → Kafka (JMX Metrics)
- 2181:2181   → Zookeeper (Management)
- 8083:8083   → Debezium Connect (REST API)
```

## データ変換ロジック

### 変換ルール定義

```python
def transform_data(source_data):
    """
    ビジネスルールに基づくデータ変換
    """
    return {
        'id': source_data['id'],                           # そのまま
        'name': f"PROCESSED_{source_data['name'].upper()}", # プレフィックス + 大文字
        'email': source_data['email'],                     # そのまま
        'age': source_data.get('age', 0) + 1,             # +1加算
        'processed_at': 'NOW()',                          # 処理時刻
        'source_table': 'tablea'                          # ソーステーブル名
    }

Operation Mapping:
- INSERT (op: 'c') → INSERT INTO tableb
- UPDATE (op: 'u') → UPSERT (INSERT ... ON CONFLICT)
- DELETE (op: 'd') → DELETE FROM tableb
- READ   (op: 'r') → スキップ（スナップショット時）
```

## 監視・ロギング

### ログ出力設定

```python
Logging Configuration:
- Level: INFO
- Format: '%(asctime)s - %(levelname)s - %(message)s'
- Output: stdout (Docker logs)

Key Log Events:
- Service startup/shutdown
- Kafka connection events
- PostgreSQL operations
- Data transformation results
- Error conditions and retries
```

### メトリクス収集ポイント

```
Performance Metrics:
1. Kafka Metrics (Port 9101):
   - Message throughput
   - Consumer lag
   - Partition distribution

2. PostgreSQL Metrics:
   - Transaction rate
   - WAL generation rate
   - Replication slot status

3. Python Application Metrics:
   - Processing latency
   - Error rates
   - Database connection pool status
```

## セキュリティ考慮事項

### 認証・認可

```yaml
Database Security:
  - User: postgres (administrative)
  - Password: postgres (development only)
  - Network: Internal Docker network only
  - SSL: Not configured (development environment)

Kafka Security:
  - Authentication: None (PLAINTEXT)
  - Authorization: None
  - Encryption: None (development environment)

Production Recommendations:
  - Database: Role-based access control
  - Kafka: SASL/SSL authentication
  - Network: TLS encryption
  - Secrets: External secret management
```

### データプライバシー

```
Data Handling:
- PII Identification: Email addresses
- Transformation: Name processing (reversible)
- Retention: Kafka topic retention policy
- Audit: Full operation logging

Privacy Controls:
- Data masking options available
- Selective field processing
- Compliance logging
- Right to be forgotten support
```

この詳細なアーキテクチャ文書により、システムの構成、データフロー、および各コンポーネントの役割を包括的に理解できます。