/*
 * Der Raspberry Pi 4 dekodiert VP9 und AV1 nur in Software - YouTube in 1080p
 * ruckelt dann mit Ladekreis, obwohl das Netz schnell genug ist. Diese
 * Erweiterung meldet YouTube, dass der Browser nur H.264 (avc1) mit hoechstens
 * 30 Bildern pro Sekunde kann. Dasselbe Prinzip wie die bekannte
 * Erweiterung "h264ify".
 */
(() => {
  const blocked = (type) => {
    if (typeof type !== "string") return false;
    if (/vp0?[89]|av01|av1\b/i.test(type)) return true;
    const fps = /framerate=(\d+)/i.exec(type);
    return !!fps && Number(fps[1]) > 30;
  };

  if (window.MediaSource && MediaSource.isTypeSupported) {
    const original = MediaSource.isTypeSupported.bind(MediaSource);
    MediaSource.isTypeSupported = (type) => !blocked(type) && original(type);
  }
  if (window.ManagedMediaSource && ManagedMediaSource.isTypeSupported) {
    const original = ManagedMediaSource.isTypeSupported.bind(ManagedMediaSource);
    ManagedMediaSource.isTypeSupported = (type) => !blocked(type) && original(type);
  }
  const canPlay = HTMLMediaElement.prototype.canPlayType;
  HTMLMediaElement.prototype.canPlayType = function (type) {
    return blocked(type) ? "" : canPlay.call(this, type);
  };
  if (navigator.mediaCapabilities && navigator.mediaCapabilities.decodingInfo) {
    const decodingInfo = navigator.mediaCapabilities.decodingInfo.bind(navigator.mediaCapabilities);
    navigator.mediaCapabilities.decodingInfo = (config) => {
      const video = config && config.video;
      if (video && (blocked(video.contentType) || (video.framerate || 0) > 30)) {
        return Promise.resolve({ supported: false, smooth: false, powerEfficient: false });
      }
      return decodingInfo(config);
    };
  }
})();
