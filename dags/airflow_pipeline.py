from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

# Nếu cần Kafka provider, pip install apache-airflow-providers-apache-kafka
# from airflow.providers.apache.kafka.hooks.kafka import KafkaHook

def fetch_data_from_kafka(**context):
    """
    Ví dụ sử dụng kafka-python để đọc messages từ topic.
    Lưu raw data xuống file /tmp/raw_data.json
    """
    from kafka import KafkaConsumer
    import json

    consumer = KafkaConsumer(
        'my_topic',
        bootstrap_servers=['192.168.28.39:9092'],
        auto_offset_reset='earliest',
        group_id='retrain_group',
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    raw = []
    for msg in consumer:
        raw.append(msg.value)
        if len(raw) >= 1000:  # hoặc điều kiện dừng
            break
    consumer.close()
    with open('/tmp/raw_data.json', 'w') as f:
        json.dump(raw, f)

def preprocess(**context):
    import json, pandas as pd
    data = json.load(open('/tmp/raw_data.json'))
    df = pd.DataFrame(data)
    # ví dụ tiền xử lý
    df = df.dropna().reset_index(drop=True)
    df.to_parquet('/tmp/processed_data.parquet')

def train_model(**context):
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier
    import joblib

    df = pd.read_parquet('/tmp/processed_data.parquet')
    X = df.drop('label', axis=1)
    y = df['label']
    model = RandomForestClassifier(n_estimators=100)
    model.fit(X, y)
    joblib.dump(model, '/tmp/model.pkl')

def evaluate_model(**context):
    import pandas as pd
    import joblib
    from sklearn.metrics import accuracy_score

    df = pd.read_parquet('/tmp/processed_data.parquet')
    X = df.drop('label', axis=1)
    y = df['label']
    model = joblib.load('/tmp/model.pkl')
    preds = model.predict(X)
    acc = accuracy_score(y, preds)
    print(f"Retrained model accuracy: {acc:.4f}")
    # Có thể push lên XCom để notify hoặc lưu log

def deploy_model(**context):
    import shutil
    # Ví dụ copy model.pkl ra thư mục production
    shutil.copy('/tmp/model.pkl', '/opt/models/current_model.pkl')

default_args = {
    'owner': 'mlops',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    dag_id='weekly_model_retraining',
    default_args=default_args,
    description='Retrain ML model weekly from Kafka data',
    schedule_interval='@weekly',  # hoặc timedelta(weeks=1)
    start_date=datetime(2025, 6, 1),
    catchup=False,
    tags=['ml', 'retrain'],
) as dag:

    t1 = PythonOperator(
        task_id='fetch_data_from_kafka',
        python_callable=fetch_data_from_kafka,
        provide_context=True,
    )

    t2 = PythonOperator(
        task_id='preprocess_data',
        python_callable=preprocess,
        provide_context=True,
    )

    t3 = PythonOperator(
        task_id='train_model',
        python_callable=train_model,
        provide_context=True,
    )

    t4 = PythonOperator(
        task_id='evaluate_model',
        python_callable=evaluate_model,
        provide_context=True,
    )

    t5 = PythonOperator(
        task_id='deploy_model',
        python_callable=deploy_model,
        provide_context=True,
    )

    # Định nghĩa thứ tự thực thi
    t1 >> t2 >> t3 >> t4 >> t5
