# kafka_producer.py

import json
from aiokafka import AIOKafkaProducer
from models import Session

class KafkaProducer:
    def __init__(self, bootstrap_servers: str = "kafka:9092"):
        self._bootstrap = bootstrap_servers
        self.producer: AIOKafkaProducer | None = None

    async def start(self):
        """
        Phải gọi trước khi send bất kỳ message nào.
        """
        self.producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap)
        await self.producer.start()

    async def send_session(self, session: Session):
        """
        Gửi một session lên topic 'session_data'.
        Trả về RecordMetadata nếu thành công, in lỗi nếu thất bại.
        """
        if self.producer is None:
            raise RuntimeError("Producer chưa được start()")
        key = session.session_id.encode("utf-8")
        value = json.dumps(session.model_dump()).encode("utf-8")
        try:
            # send_and_wait trả về RecordMetadata
            meta = await self.producer.send_and_wait(
                "session_data", key=key, value=value
            )
            print(
                f"Delivered to {meta.topic} "
                f"[partition {meta.partition}] @ offset {meta.offset}"
            )
        except Exception as e:
            print(f"Failed to deliver message: {e}")

    async def stop(self):
        """
        Đóng producer, flush tất cả messages.
        """
        if self.producer:
            await self.producer.stop()
            self.producer = None

