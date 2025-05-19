from confluent_kafka import Producer
import json
from models import Session

class KafkaProducer:
    def __init__(self, bootstrap_servers="kafka:9092"):
        self.producer = Producer({"bootstrap.servers": bootstrap_servers})

    def delivery_report(self, err, msg):
        if err is not None:
            print(f"Message delivery failed: {err}")
        else:
            print(f"Message delivered to {msg.topic()} [{msg.partition()}]")

    def send_session(self, session: Session):
        topic = "session_data"
        self.producer.produce(
            topic,
            key=session.session_id.encode("utf-8"),
            value=json.dumps(session.dict()).encode("utf-8"),
            callback=self.delivery_report
        )
        self.producer.flush()