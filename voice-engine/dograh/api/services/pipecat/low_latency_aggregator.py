from pipecat.frames.frames import Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from loguru import logger

class LowLatencyAggregator(FrameProcessor):
    """
    Implements Fix 1 from the Latency Optimization Guide:
    - First chunk fires at 30 chars (speed).
    - Subsequent chunks fire at sentence boundaries (quality).
    - Never waits more than 80 chars regardless.
    """
    def __init__(self):
        super().__init__()
        self._buffer = ""
        self._first_chunk_sent = False
        self._FIRST_THRESHOLD = 30   # fast first audio
        self._HARD_MAX = 80          # never hold longer than this
        self._sentence_terminators = {".", "!", "?", ",", ";", ":"}

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame):
            self._buffer += frame.text
            if self._should_flush():
                text = self._flush()
                if text:
                    await self.push_frame(TextFrame(text), direction)
        else:
            # For non-text frames, flush buffer first to maintain order
            if self._buffer:
                text = self._flush()
                if text:
                    await self.push_frame(TextFrame(text), direction)
            await self.push_frame(frame, direction)

    def _should_flush(self) -> bool:
        cleaned_buffer = self._buffer.strip()
        if not cleaned_buffer:
            return False
            
        # First chunk: fire fast even mid-sentence
        if not self._first_chunk_sent and len(cleaned_buffer) >= self._FIRST_THRESHOLD:
            return True
            
        # Subsequent: wait for natural boundary
        if cleaned_buffer[-1:] in self._sentence_terminators:
            return True
            
        # Hard cap: never buffer more than HARD_MAX
        if len(cleaned_buffer) >= self._HARD_MAX:
            return True
            
        return False

    def _flush(self) -> str:
        text = self._buffer.strip()
        self._buffer = ""
        if text:
            self._first_chunk_sent = True
        return text

    async def _handle_interruption(self):
        self._buffer = ""
        self._first_chunk_sent = False
