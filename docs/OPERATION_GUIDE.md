# Debezium CDC System - 動作確認・運用ガイド

## 目次
1. [システム起動手順](#システム起動手順)
2. [基本動作確認](#基本動作確認)
3. [データ変更テスト](#データ変更テスト)
4. [監視・診断](#監視診断)
5. [トラブルシューティング](#トラブルシューティング)
6. [運用・保守](#運用保守)

## システム起動手順

### 1. 前提条件確認
```bash
# Docker環境の確認
docker --version
docker-compose --version

# 必要なポートが使用されていないことを確認
netstat -tuln | grep -E ":(5432|9092|8083|2181)"
```

### 2. システム起動
```bash
# プロジェクトディレクトリに移動
cd /path/to/debezium

# バックグラウンドで全サービス起動
docker-compose up -d

# 起動状況確認
docker-compose ps
```

### 3. 起動完了確認
```bash
# 全サービスが「Up」状態であることを確認
docker-compose ps

# 期待する出力例:
# NAME                       IMAGE                             COMMAND                  SERVICE         CREATED         STATUS         PORTS
# debezium-postgres-1        postgres:17                      "docker-entrypoint.s…"   postgres        1 minute ago    Up 1 minute    0.0.0.0:5432->5432/tcp
# debezium-zookeeper-1       confluentinc/cp-zookeeper:7.4.0   "/etc/confluent/dock…"   zookeeper       1 minute ago    Up 1 minute    0.0.0.0:2181->2181/tcp
# debezium-kafka-1           confluentinc/cp-kafka:7.4.0       "/etc/confluent/dock…"   kafka           1 minute ago    Up 1 minute    0.0.0.0:9092->9092/tcp
# debezium-connect-1         debezium/connect:2.4              "/docker-entrypoint.…"   connect         1 minute ago    Up 1 minute    0.0.0.0:8083->8083/tcp
# debezium-cdc-processor-1   debezium-cdc-processor            "python cdc_processo…"   cdc-processor   1 minute ago    Up 1 minute
```

## 基本動作確認

### 1. PostgreSQL接続確認
```bash
# データベースへの接続テスト
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "SELECT version();"

# 初期テーブル確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'public';"
```

### 2. 初期データ確認
```bash
# tableA（ソーステーブル）の確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT id, name, email, age, created_at
FROM tablea
ORDER BY id;"

# tableB（宛先テーブル）の確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT id, name, email, age, processed_at, source_table
FROM tableb
ORDER BY id;"
```

### 3. Kafka環境確認
```bash
# Kafkaトピック一覧確認
docker exec debezium-kafka-1 kafka-topics --bootstrap-server localhost:9092 --list

# 期待するトピック:
# - cdc.tablea
# - my_connect_configs
# - my_connect_offsets
# - my_connect_statuses
# - schema-changes.testdb
```

### 4. Debezium Connect確認
```bash
# Connect API動作確認
curl -s http://localhost:8083/

# コネクタ一覧確認
curl -s http://localhost:8083/connectors

# postgres-connectorの状態確認
curl -s http://localhost:8083/connectors/postgres-connector/status | jq '.'
```

### 5. Python CDCプロセッサ確認
```bash
# プロセッサのログ確認（最新10行）
docker logs debezium-cdc-processor-1 --tail 10

# リアルタイムログ監視
docker logs -f debezium-cdc-processor-1
```

## データ変更テスト

### テスト1: INSERT操作
```bash
# 新規レコード挿入
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
INSERT INTO tablea (name, email, age)
VALUES ('テストユーザー', 'test@example.com', 25);"

# 3秒待機してから結果確認
sleep 3

# 変換されたデータがtableBに挿入されているか確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT * FROM tableb
WHERE email = 'test@example.com';"

# 期待する結果: name = 'PROCESSED_テストユーザー', age = 26
```

### テスト2: UPDATE操作
```bash
# 既存レコードの更新
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
UPDATE tablea
SET name = '更新されたユーザー', age = 30
WHERE email = 'test@example.com';"

# 結果確認
sleep 3
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT * FROM tableb
WHERE email = 'test@example.com';"

# 期待する結果: name = 'PROCESSED_更新されたユーザー', age = 31
```

### テスト3: DELETE操作
```bash
# レコード削除前の状態確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT COUNT(*) as count_before FROM tableb
WHERE email = 'test@example.com';"

# レコード削除
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
DELETE FROM tablea
WHERE email = 'test@example.com';"

# 削除後の確認
sleep 3
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT COUNT(*) as count_after FROM tableb
WHERE email = 'test@example.com';"

# 期待する結果: count_after = 0
```

### テスト4: 一括操作
```bash
# 複数レコードの一括挿入
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
INSERT INTO tablea (name, email, age) VALUES
('一括ユーザー1', 'bulk1@example.com', 20),
('一括ユーザー2', 'bulk2@example.com', 25),
('一括ユーザー3', 'bulk3@example.com', 30);"

# 処理結果確認
sleep 5
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT name, age, processed_at
FROM tableb
WHERE email LIKE 'bulk%@example.com'
ORDER BY processed_at;"
```

## 監視・診断

### 1. システム状態確認
```bash
# 全コンテナのリソース使用状況
docker stats --no-stream

# 個別コンテナのログ確認
docker logs debezium-postgres-1 --tail 20
docker logs debezium-kafka-1 --tail 20
docker logs debezium-connect-1 --tail 20
docker logs debezium-cdc-processor-1 --tail 20
```

### 2. Kafka監視
```bash
# トピック詳細情報
docker exec debezium-kafka-1 kafka-topics --bootstrap-server localhost:9092 --describe --topic cdc.tablea

# コンシューマーグループの状態
docker exec debezium-kafka-1 kafka-consumer-groups --bootstrap-server localhost:9092 --list

# CDCプロセッサのオフセット確認
docker exec debezium-kafka-1 kafka-consumer-groups --bootstrap-server localhost:9092 --describe --group cdc-processor-group
```

### 3. PostgreSQL監視
```bash
# レプリケーションスロット確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT slot_name, plugin, slot_type, database, active, confirmed_flush_lsn
FROM pg_replication_slots;"

# WAL統計確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT * FROM pg_stat_wal;"

# アクティブな接続確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT datname, usename, application_name, client_addr, state
FROM pg_stat_activity
WHERE datname = 'testdb';"
```

### 4. Debezium監視
```bash
# コネクタのメトリクス確認
curl -s http://localhost:8083/connectors/postgres-connector/status | jq '.tasks[0]'

# コネクタ設定確認
curl -s http://localhost:8083/connectors/postgres-connector/config | jq '.'

# コネクタの再起動（必要に応じて）
curl -X POST http://localhost:8083/connectors/postgres-connector/restart
```

## トラブルシューティング

### 問題1: コンテナが起動しない
```bash
# エラーログ確認
docker-compose logs [service-name]

# よくある解決策:
# 1. ポート競合確認
netstat -tuln | grep -E ":(5432|9092|8083|2181)"

# 2. ディスク容量確認
df -h

# 3. メモリ使用量確認
free -h

# 4. 完全クリーンアップして再起動
docker-compose down -v
docker system prune -f
docker-compose up -d
```

### 問題2: CDCが動作しない
```bash
# 1. Debeziumコネクタの状態確認
curl -s http://localhost:8083/connectors/postgres-connector/status

# 2. Kafkaトピックにメッセージが届いているか確認
docker exec debezium-kafka-1 kafka-console-consumer --bootstrap-server localhost:9092 --topic cdc.tablea --from-beginning --max-messages 5

# 3. PostgreSQLレプリケーション設定確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "SHOW wal_level;"

# 4. Python CDCプロセッサの詳細ログ確認
docker logs debezium-cdc-processor-1 | grep -E "(ERROR|Exception|Failed)"
```

### 問題3: データ変換エラー
```bash
# Python CDCプロセッサのエラーログ確認
docker logs debezium-cdc-processor-1 | tail -50

# データベース接続エラーの場合
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT * FROM pg_stat_activity WHERE state = 'active';"

# コンテナ再起動
docker-compose restart cdc-processor
```

### 問題4: パフォーマンス問題
```bash
# 1. Kafkaコンシューマーラグ確認
docker exec debezium-kafka-1 kafka-consumer-groups --bootstrap-server localhost:9092 --describe --group cdc-processor-group

# 2. PostgreSQL性能確認
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
ORDER BY total_time DESC LIMIT 10;"

# 3. リソース使用状況
docker stats
```

## 運用・保守

### 定期メンテナンス

#### 日次確認項目
```bash
#!/bin/bash
# daily_check.sh

echo "=== 日次ヘルスチェック $(date) ==="

# 1. コンテナ状態確認
echo "1. コンテナ状態:"
docker-compose ps

# 2. ディスク使用量確認
echo "2. ディスク使用量:"
df -h

# 3. CDCプロセッサのエラーチェック
echo "3. 過去24時間のエラー:"
docker logs debezium-cdc-processor-1 --since 24h | grep -c ERROR

# 4. レプリケーションスロット確認
echo "4. レプリケーションスロット:"
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "
SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) as lag
FROM pg_replication_slots;"

echo "=== チェック完了 ==="
```

#### 週次メンテナンス
```bash
#!/bin/bash
# weekly_maintenance.sh

echo "=== 週次メンテナンス $(date) ==="

# 1. ログローテーション
docker exec debezium-postgres-1 psql -U postgres -c "SELECT pg_rotate_logfile();"

# 2. 不要なDockerイメージ削除
docker image prune -f

# 3. PostgreSQL統計情報更新
docker exec debezium-postgres-1 psql -U postgres -d testdb -c "ANALYZE;"

# 4. バックアップ実行
pg_dump -h localhost -p 5432 -U postgres testdb > backup_$(date +%Y%m%d).sql

echo "=== メンテナンス完了 ==="
```

### データバックアップ
```bash
# 完全バックアップ
docker exec debezium-postgres-1 pg_dump -U postgres testdb > full_backup_$(date +%Y%m%d_%H%M%S).sql

# 差分バックアップ（WALファイル）
docker exec debezium-postgres-1 pg_basebackup -D /backup -Ft -z -P -U postgres

# データ復元例
# docker exec -i debezium-postgres-1 psql -U postgres testdb < backup_file.sql
```

### システム停止
```bash
# 通常停止（graceful shutdown）
docker-compose down

# 強制停止
docker-compose kill

# データ込みで完全削除
docker-compose down -v

# システム全体クリーンアップ
docker-compose down -v
docker system prune -f
docker volume prune -f
```

### パフォーマンスチューニング
```bash
# PostgreSQL設定調整例
# postgresql.conf の主要パラメータ:
# - shared_buffers = 256MB → 512MB
# - effective_cache_size = 1GB → 2GB
# - max_wal_size = 1GB → 2GB
# - checkpoint_completion_target = 0.9

# Kafka設定調整例（高スループット環境）
# docker-compose.yml のKafka環境変数:
# - KAFKA_NUM_NETWORK_THREADS: 8
# - KAFKA_NUM_IO_THREADS: 16
# - KAFKA_SOCKET_SEND_BUFFER_BYTES: 102400
# - KAFKA_SOCKET_RECEIVE_BUFFER_BYTES: 102400
```

このガイドを使用して、システムの正常な動作確認と継続的な運用を行ってください。問題が発生した場合は、該当するトラブルシューティングセクションを参照してください。