# Debezium CDC システム

PostgreSQLのtableAの変更をDebeziumでキャプチャし、Pythonで加工してtableBにinsertするシステムです。

## アーキテクチャ

![](./docs/architecture.svg)

```
PostgreSQL (tableA) → Debezium → Kafka → Python Processor → PostgreSQL (tableB)
```

## 構成要素

- **PostgreSQL**: ソースデータベース（tableA）と宛先データベース（tableB）
- **Apache Kafka**: メッセージブローカー
- **Zookeeper**: Kafkaの協調サービス
- **Debezium Connect**: PostgreSQL CDC コネクタ
- **Python CDC Processor**: データ変換・処理アプリケーション

## セットアップと起動

### 1. システム起動

```bash
docker-compose up -d
```

### 2. 起動確認

各サービスが起動するまで少し時間がかかります。以下のコマンドでステータスを確認：

```bash
docker-compose ps
```

### 3. ログ確認

```bash
# 全体のログ
docker-compose logs -f

# Python CDCプロセッサのログ
docker-compose logs -f cdc-processor

# Debezium Connectのログ
docker-compose logs -f connect
```

## テスト方法

### 1. 初期データ確認

```bash
# PostgreSQLに接続
docker exec -it debezium-postgres-1 psql -U postgres -d testdb

# tableAの確認
SELECT * FROM tablea;

# tableBの確認
SELECT * FROM tableb;
```

### 2. データ変更のテスト

#### INSERT テスト
```sql
INSERT INTO tablea (name, email, age) VALUES ('新規ユーザー', 'newuser@example.com', 28);
```

#### UPDATE テスト
```sql
UPDATE tablea SET name = '更新されたユーザー', age = 26 WHERE id = 1;
```

#### DELETE テスト
```sql
DELETE FROM tablea WHERE id = 2;
```

### 3. 処理結果確認

各操作後にtableBを確認して、データが正しく変換・挿入されているかチェック：

```sql
SELECT * FROM tableb ORDER BY processed_at DESC;
```

## データ変換ルール

Python CDC Processorは以下の変換を行います：

- **name**: 大文字に変換し、`PROCESSED_`プレフィックスを追加
- **age**: 元の値に+1
- **processed_at**: 処理時刻を記録
- **source_table**: ソーステーブル名（'tablea'）を記録

## トラブルシューティング

### Debezium Connectorの状態確認

```bash
# コネクタ一覧
curl http://localhost:8083/connectors

# コネクタ詳細
curl http://localhost:8083/connectors/postgres-connector

# コネクタステータス
curl http://localhost:8083/connectors/postgres-connector/status
```

### Kafkaトピック確認

```bash
# トピック一覧
docker exec debezium-kafka-1 kafka-topics --bootstrap-server localhost:9092 --list

# メッセージ確認
docker exec debezium-kafka-1 kafka-console-consumer --bootstrap-server localhost:9092 --topic cdc.tablea --from-beginning
```

### PostgreSQL レプリケーションスロット確認

```bash
docker exec -it debezium-postgres-1 psql -U postgres -d testdb -c "SELECT * FROM pg_replication_slots;"
```

## システム停止

```bash
docker-compose down

# データも削除する場合
docker-compose down -v
```

## ファイル構成

```
├── compose.yml
├── Dockerfile.python
├── init.sql
├── postgresql.conf
├── README.md
├── requirements.txt
├── debezium-config/
│   └── postgres-connector.json
├── docs/
│   ├── architecture.drawio
│   ├── ARCHITECTURE.md
│   ├── OPERATION_GUIDE.md
│   └── SYSTEM_OVERVIEW.md
└── python-app/
    └── cdc_processor.py
```
