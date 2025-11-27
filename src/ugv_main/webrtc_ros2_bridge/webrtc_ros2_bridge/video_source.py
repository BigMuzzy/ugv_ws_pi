"""Video source for capturing camera frames."""
import asyncio
import fractions
import threading
import time

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    from av import VideoFrame
    AV_AVAILABLE = True
except ImportError:
    AV_AVAILABLE = False


class VideoSource:
    """Capture video from camera device for WebRTC streaming."""

    def __init__(
        self,
        device="/dev/video0",
        width=640,
        height=480,
        fps=30,
        logger=None
    ):
        """
        Initialize video source.

        Args:
            device: Camera device path or index
            width: Frame width
            height: Frame height
            fps: Target frames per second
            logger: Logger instance for messages
        """
        self._device = device
        self._width = width
        self._height = height
        self._fps = fps
        self._logger = logger

        self._capture = None
        self._running = False
        self._frame = None
        self._lock = threading.Lock()
        self._frame_count = 0
        self._start_time = None

        if not CV2_AVAILABLE:
            if self._logger:
                self._logger.error("OpenCV not available for video capture")

    def start(self):
        """Start video capture."""
        if not CV2_AVAILABLE:
            return False

        try:
            # Try to open as device index if it's a number
            if isinstance(self._device, int):
                device_id = self._device
            elif self._device.startswith("/dev/video"):
                device_id = int(self._device.replace("/dev/video", ""))
            else:
                device_id = 0

            self._capture = cv2.VideoCapture(device_id)

            if not self._capture.isOpened():
                if self._logger:
                    self._logger.error(f"Failed to open camera: {self._device}")
                return False

            # Set capture properties
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            self._capture.set(cv2.CAP_PROP_FPS, self._fps)

            self._running = True
            self._start_time = time.time()
            self._frame_count = 0

            if self._logger:
                actual_w = self._capture.get(cv2.CAP_PROP_FRAME_WIDTH)
                actual_h = self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
                actual_fps = self._capture.get(cv2.CAP_PROP_FPS)
                self._logger.info(
                    f"Camera started: {actual_w}x{actual_h} @ {actual_fps}fps"
                )

            return True

        except Exception as e:
            if self._logger:
                self._logger.error(f"Error starting camera: {e}")
            return False

    def stop(self):
        """Stop video capture."""
        self._running = False
        if self._capture:
            self._capture.release()
            self._capture = None

    def get_frame(self):
        """
        Get the latest frame.

        Returns:
            numpy array of frame or None if not available
        """
        if not self._capture or not self._running:
            return None

        ret, frame = self._capture.read()
        if ret:
            self._frame_count += 1
            return frame
        return None

    def get_frame_rgb(self):
        """
        Get the latest frame in RGB format.

        Returns:
            numpy array of frame in RGB or None
        """
        frame = self.get_frame()
        if frame is not None and CV2_AVAILABLE:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return None

    @property
    def fps(self):
        """Return configured FPS."""
        return self._fps

    @property
    def width(self):
        """Return configured width."""
        return self._width

    @property
    def height(self):
        """Return configured height."""
        return self._height

    @property
    def is_running(self):
        """Return whether capture is running."""
        return self._running


class VideoStreamTrack:
    """
    Video stream track for WebRTC.

    This class provides frames from the VideoSource in a format
    suitable for aiortc MediaStreamTrack.
    """

    kind = "video"

    def __init__(self, video_source, logger=None):
        """
        Initialize video stream track.

        Args:
            video_source: VideoSource instance
            logger: Logger instance
        """
        self._source = video_source
        self._logger = logger
        self._timestamp = 0
        self._time_base = fractions.Fraction(1, 90000)

    async def recv(self):
        """
        Receive next video frame.

        Returns:
            VideoFrame or None
        """
        if not AV_AVAILABLE or not NUMPY_AVAILABLE:
            await asyncio.sleep(1.0 / self._source.fps)
            return None

        # Get frame from camera
        frame_rgb = self._source.get_frame_rgb()

        if frame_rgb is None:
            # Return a black frame if camera not available
            frame_rgb = np.zeros(
                (self._source.height, self._source.width, 3),
                dtype=np.uint8
            )

        # Create VideoFrame
        frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")

        # Set timestamp
        frame.pts = self._timestamp
        frame.time_base = self._time_base
        self._timestamp += int(90000 / self._source.fps)

        # Sleep to maintain frame rate
        await asyncio.sleep(1.0 / self._source.fps)

        return frame

    def stop(self):
        """Stop the video track."""
        pass


def create_test_pattern(width=640, height=480):
    """
    Create a test pattern frame for testing without camera.

    Args:
        width: Frame width
        height: Frame height

    Returns:
        numpy array with test pattern
    """
    if not NUMPY_AVAILABLE:
        return None

    # Create a simple color bar test pattern
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    bar_width = width // 8

    colors = [
        (255, 255, 255),  # White
        (255, 255, 0),    # Yellow
        (0, 255, 255),    # Cyan
        (0, 255, 0),      # Green
        (255, 0, 255),    # Magenta
        (255, 0, 0),      # Red
        (0, 0, 255),      # Blue
        (0, 0, 0),        # Black
    ]

    for i, color in enumerate(colors):
        x_start = i * bar_width
        x_end = (i + 1) * bar_width
        frame[:, x_start:x_end] = color

    return frame
