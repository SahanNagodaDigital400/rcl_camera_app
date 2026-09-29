/**
 * The rear camera, opened once and owned by whichever screen is holding it.
 *
 * **One implementation, because the two screens that photograph a tile have to
 * photograph it the same way.** `ScanScreen` matches a tile and `MeasureScreen`
 * measures one; they want different crops out of the frame, but they want the
 * same frame — the same `getUserMedia` constraints, the same permission
 * choreography, the same canvas encode on the way out. Two copies of this kept
 * in step by hand is how they came to differ before: measuring went through
 * `<input type="file" capture="environment">`, which hands back the camera
 * app's own file with its EXIF orientation intact, while matching went through
 * a canvas re-encode that bakes the rotation into the pixels. The server
 * honoured one and the browser honoured the other, and a photograph taken with
 * the phone turned measured as a tile lying on its side.
 *
 * So the constraint block, the permission probe and the stream's lifetime live
 * here, and a screen supplies only what it does with the frame.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Where a screen is between "never asked" and "the viewfinder is live."
 *
 * `'checking'` is the arrival wait while the Permissions API answers;
 * `'starting'` is the already-granted case, the request being made on
 * arrival — neither flashes the explanation before the viewfinder.
 * `'requesting'` is the same wait after a tap, and disables the one button
 * that could fire a second concurrent `getUserMedia` call while the first is
 * resolving.
 */
export type CameraState =
  | 'unrequested'
  | 'checking'
  | 'starting'
  | 'requesting'
  | 'granted'
  | 'denied';

/**
 * Whether the Permissions API is there to be asked. Decided synchronously so
 * the first render already knows whether to show the explanation or a short
 * "checking" wait — no flash of one before the other.
 */
export function canQueryPermission(): boolean {
  return typeof navigator.permissions?.query === 'function';
}

/**
 * Whether the browser has already granted camera access, so `getUserMedia`
 * would open the viewfinder without a prompt. `false` whenever the answer is
 * anything else — `'prompt'`, `'denied'`, an unsupported name, a browser
 * without the API — because in every one of those cases the right move is to
 * explain and wait for a tap.
 */
async function cameraAlreadyGranted(): Promise<boolean> {
  try {
    // `'camera'` is a real permission name in every current engine but is
    // still missing from TypeScript's `PermissionName` union.
    const status = await navigator.permissions.query({ name: 'camera' as PermissionName });
    return status.state === 'granted';
  } catch {
    return false;
  }
}

export interface RearCamera {
  cameraState: CameraState;
  /**
   * Attach the live stream to the `<video>` that renders it.
   *
   * A callback ref rather than an object ref, and that is what makes a screen
   * free to unmount the viewfinder and bring it back — `MeasureScreen` swaps
   * it for the photograph it just took and returns to it on Retake. An effect
   * keyed on `cameraState` alone would not fire on that remount, and the
   * viewfinder would come back black with the camera still running.
   */
  attachVideo: (element: HTMLVideoElement | null) => void;
  /** The first-visit tap: show the wait, then ask. */
  enableCamera: () => void;
  /** The frame source a capture draws from, or `null` before one is live. */
  videoElement: () => HTMLVideoElement | null;
}

export function useRearCamera(): RearCamera {
  const [cameraState, setCameraState] = useState<CameraState>(() =>
    canQueryPermission() ? 'checking' : 'unrequested',
  );
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // `true` while the holding screen is in the document, so a `getUserMedia`
  // call still in flight when it leaves knows, once it resolves, that storing
  // its stream and flipping state would both be pointless.
  const mountedRef = useRef(true);
  // One camera request at a time: StrictMode runs the mount effect twice and
  // a fast double tap fires the button twice, and either would otherwise open
  // two streams and keep the hardware light on for the one nobody holds.
  const requestingRef = useRef(false);

  const requestCamera = useCallback(async (): Promise<void> => {
    if (requestingRef.current) return;
    requestingRef.current = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        // **A resolution is asked for, and that is not a refinement.** A bare
        // `facingMode` constraint lets the engine pick, and several pick
        // 640x480 — on which the shutter's centre square is 480x480, a marker
        // filling a sixth of the frame is ~77px, and `api.measure` refuses it
        // under 60. That is the "marker is too small" a real showroom photo
        // hits while the same tile measures fine from a gallery file, which
        // carries the sensor's own resolution.
        //
        // `ideal` rather than `min`, so a device that cannot reach it still
        // opens the viewfinder rather than failing the whole request — the
        // one thing worse than a low-resolution scan is no camera at all.
        // Both axes carry the same number because a phone held upright
        // reports the stream portrait, and asking for a landscape shape would
        // have the engine pick the closest mode to the wrong aspect.
        //
        // Matching is unaffected in every way but sharpness: the centre
        // square is still taken at the sensor's resolution and still spends
        // the same ~1024px budget, so nothing about `shared/vision` or the
        // index changes — the pixels going into it are simply better.
        video: {
          facingMode: 'environment',
          width: { ideal: 1920 },
          height: { ideal: 1920 },
        },
        audio: false,
      });
      if (!mountedRef.current) {
        // The screen was left while the permission prompt was still up.
        // Nothing downstream will ever read `streamRef` again, so the only
        // thing left to do is turn the hardware light back off.
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      if (videoRef.current !== null) videoRef.current.srcObject = stream;
      setCameraState('granted');
    } catch {
      // Whatever the reason — denied, no camera present, an insecure origin —
      // the fallback is the same, and EXPERIENCE.md draws no distinction
      // between "denied" and "denied previously" either.
      if (mountedRef.current) setCameraState('denied');
    } finally {
      requestingRef.current = false;
    }
  }, []);

  const enableCamera = useCallback((): void => {
    setCameraState('requesting');
    void requestCamera();
  }, [requestCamera]);

  const attachVideo = useCallback((element: HTMLVideoElement | null): void => {
    videoRef.current = element;
    // The stream may already be live — a remounted viewfinder, or a grant
    // that resolved before this element existed. Binding here covers that
    // order; the effect below covers the other.
    if (element !== null) element.srcObject = streamRef.current;
  }, []);

  const videoElement = useCallback((): HTMLVideoElement | null => videoRef.current, []);

  /**
   * On arrival, ask the browser whether camera access is already granted and
   * start the camera if so; on the way out, stop every track.
   *
   * The Permissions API is the external system this effect synchronises
   * with; every state change here happens in its answer's `then`, never
   * synchronously in the effect body. A `'prompt'` or `'denied'` answer — or
   * no API at all — leaves the explanation and its tap in place.
   *
   * A `MediaStream` keeps the camera's hardware light on until its tracks are
   * stopped explicitly — letting React garbage-collect the object does
   * nothing for the physical LED. The cleanup fires on Back, on a submission
   * handing off to Results, and on a sign-out, because all three unmount the
   * holding component the same way.
   */
  useEffect(() => {
    mountedRef.current = true;
    if (canQueryPermission()) {
      void cameraAlreadyGranted().then((granted) => {
        if (!mountedRef.current) return;
        if (granted) {
          setCameraState('starting');
          void requestCamera();
        } else {
          setCameraState('unrequested');
        }
      });
    }

    return () => {
      mountedRef.current = false;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, [requestCamera]);

  /**
   * Bind the stream to the `<video>` element once both exist.
   *
   * `<video>` renders exclusively in the `'granted'` branch, so the element is
   * not yet mounted at the moment `enableCamera`'s `await` resolves. Running
   * the assignment from an effect keyed on `cameraState` guarantees it happens
   * after the render that mounts the element; `attachVideo` covers the reverse
   * order, and both are idempotent.
   */
  useEffect(() => {
    if (cameraState === 'granted' && videoRef.current !== null) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [cameraState]);

  return { cameraState, attachVideo, enableCamera, videoElement };
}
