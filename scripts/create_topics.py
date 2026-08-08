import asyncio

from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from scam2market.config.settings import get_settings
from scam2market.streaming.topics import INITIAL_TOPICS, TOPIC_PARTITIONS


async def main() -> None:
    settings = get_settings()
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.redpanda_bootstrap_servers)
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        topics = [
            NewTopic(
                name=topic,
                num_partitions=TOPIC_PARTITIONS.get(topic, 3),
                replication_factor=1,
            )
            for topic in INITIAL_TOPICS
            if topic not in existing
        ]
        if topics:
            await admin.create_topics(topics)
            print(f"created topics: {[topic.name for topic in topics]}")
        else:
            print("all initial topics already exist")
    finally:
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
