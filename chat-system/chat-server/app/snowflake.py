import time
import threading


class SnowflakeGenerator:
    """
    64-bit Snowflake ID generator.
    Bit layout: 1 (sign) | 41 (timestamp) | 10 (node_id) | 12 (sequence)
    """

    EPOCH = 1700000000000  # Custom epoch: 2023-11-14

    def __init__(self, node_id: int = 1):
        if node_id < 0 or node_id > 1023:
            raise ValueError("node_id must be between 0 and 1023")
        self.node_id = node_id
        self.sequence = 0
        self.last_timestamp = -1
        self.lock = threading.Lock()

    def _current_millis(self) -> int:
        return int(time.time() * 1000)

    def generate(self) -> int:
        with self.lock:
            timestamp = self._current_millis()

            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & 0xFFF
                if self.sequence == 0:
                    # Sequence exhausted, wait for next millisecond
                    while timestamp <= self.last_timestamp:
                        timestamp = self._current_millis()
            else:
                self.sequence = 0

            if timestamp < self.last_timestamp:
                raise RuntimeError(
                    f"Clock moved backwards. Refusing to generate ID for "
                    f"{self.last_timestamp - timestamp}ms"
                )

            self.last_timestamp = timestamp
            msg_id = ((timestamp - self.EPOCH) << 22) | (self.node_id << 12) | self.sequence
            return msg_id


# Singleton instance
generator = SnowflakeGenerator(node_id=1)
