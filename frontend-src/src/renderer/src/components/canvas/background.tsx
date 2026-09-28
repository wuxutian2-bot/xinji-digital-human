import { Box, Image } from '@chakra-ui/react';
import { memo, useEffect, useRef } from 'react';
import { canvasStyles } from './canvas-styles';
import { useCamera } from '@/context/camera-context';
import { useBgUrl } from '@/context/bgurl-context';
import { useWebSocket } from '@/context/websocket-context';

const Background = memo(({ children }: { children?: React.ReactNode }) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const {
    backgroundStream, isBackgroundStreaming, startBackgroundCamera, stopBackgroundCamera,
  } = useCamera();
  const { useCameraBackground, backgroundUrl, setBackgroundUrl } = useBgUrl();
  const { baseUrl } = useWebSocket();

  const recoverBackground = () => {
    const configuredDefault = `${baseUrl}/bg/ceiling-window-room-night.jpeg`;
    const localDefault = '/bg/ceiling-window-room-night.jpeg';
    if (backgroundUrl !== configuredDefault && backgroundUrl !== localDefault) {
      setBackgroundUrl(configuredDefault);
    } else if (backgroundUrl === configuredDefault && window.location.protocol.startsWith('http')) {
      setBackgroundUrl(localDefault);
    }
  };

  useEffect(() => {
    if (useCameraBackground) {
      startBackgroundCamera();
    } else {
      stopBackgroundCamera();
    }
  }, [useCameraBackground, startBackgroundCamera, stopBackgroundCamera]);

  useEffect(() => {
    if (videoRef.current && backgroundStream) {
      videoRef.current.srcObject = backgroundStream;
    }
  }, [backgroundStream]);

  return (
    <Box {...canvasStyles.background.container}>
      {useCameraBackground ? (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          style={{
            ...canvasStyles.background.video,
            display: isBackgroundStreaming ? 'block' : 'none',
            transform: 'scaleX(-1)',
          }}
        />
      ) : (
        <Image
          {...canvasStyles.background.image}
          src={backgroundUrl}
          alt="background"
          onError={recoverBackground}
        />
      )}
      {children}
    </Box>
  );
});

Background.displayName = 'Background';

export default Background;
