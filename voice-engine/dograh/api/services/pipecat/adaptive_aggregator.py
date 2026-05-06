from pipecat.frames.frames import EndFrame, Frame, InterimTranscriptionFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.string import match_endofsentence

class AdaptiveSentenceAggregator(FrameProcessor):
    """
    Aggregates text frames into chunks optimized for both speed and quality.
    First chunk fires at first_threshold (speed).
    Subsequent chunks fire at sentence boundaries (quality).
    Never waits more than hard_max regardless.
    """
    def __init__(self, first_threshold=30, hard_max=80):
        super().__init__()
        self._aggregation = ""
        self._first_chunk_sent = False
        self._first_threshold = first_threshold
        self._hard_max = hard_max

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterimTranscriptionFrame):
            return

        if isinstance(frame, TextFrame):
            self._aggregation += frame.text
            if self._should_flush():
                await self.push_frame(TextFrame(self._aggregation))
                self._aggregation = ""
                self._first_chunk_sent = True
        elif isinstance(frame, EndFrame):
            if self._aggregation:
                await self.push_frame(TextFrame(self._aggregation))
            await self.push_frame(frame)
            self._aggregation = ""
            self._first_chunk_sent = False
        else:
            await self.push_frame(frame, direction)

    def _should_flush(self) -> bool:
        if not self._aggregation:
            return False
            
        # First chunk: fire fast even mid-sentence
        if not self._first_chunk_sent and len(self._aggregation) >= self._first_threshold:
            return True
        # Subsequent: wait for natural boundary
        if match_endofsentence(self._aggregation):
            return True
        # Hard cap: never buffer more than hard_max
        if len(self._aggregation) >= self._hard_max:
            return True
        return False
