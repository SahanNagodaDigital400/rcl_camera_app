import { useEffect, useId, useRef, useState } from 'react';
import type { ChangeEvent, JSX } from 'react';

import { computeDownscaledDimensions, downscaleToBlob } from '../scan/downscaleImage';
import styles from './ScanScreen.module.css';

/**
 * Scan — the entry point to Epic 3's crop/match pipeline (Story 3.1).
 *
 * Two ways in, converging on one output: a live camera capture and a chosen
 * file both end up calling `downscaleImage`'s two functions in the same
 * order, so the Blob `onCaptured` receives is identical in shape whichever
 * path produced it (the story's own definition of "equivalent submission").
 * Neither path does anything this screen does not do for the other — there is
 * no crop, no blur check and no upload here; those are Stories 3.2–3.4, and
 * this screen hands its Blob to a `CropScreen` that does nothing with it yet.
 *
 * **Permission sequencing is the one behavioural rule this screen exists to
 * hold.** `getUserMedia` is called from exactly one place — `enableCamera`,
 * reached only by an explicit tap on "Enable camera" — and never from an
 * effect on mount. EXPERIENCE.md's State Patterns row for "Camera permission
 * not yet granted" asks for the explanation to precede the browser's native
 * prompt every time, and the only way to guarantee that ordering across every
 * browser (Safari has no Permissions API to feature-detect past-grants with)
 * is to never call it except in direct response to a tap.
 *
 * **"Choose a photo" is never gated on the camera.** It renders in every
 * state — before a request, while one is in flight, after a grant, after a
 * denial — because EXPERIENCE.md's Accessibility Floor treats camera denial
 * as a state with a first-class fallback, never a dead end.
 *
 * **The framing guide is decorative only.** DESIGN.md's `framing-guide-overlay`
 * block is an accent outline with a transparent fill; there is no blur or
 * framing analysis behind it; that is Story 3.3.
 *
 * **Content decides, never the extension** — `AddTileScreen`'s own rule,
 * applied here to the file picker: `accept="image/*"` is a hint to the
 * picker, not a check, and only a genuine decode failure (`createImageBitmap`
 * rejecting) produces the inline error. A `.tif` behind a `.jpg` name is not
 * pre-judged.
 */

const CAMERA_EXPLANATION =
  'Rocell Tile Scanner needs your camera to photograph a tile. Nothing is captured until you tap the shutter.';

const CAMERA_DENIED =
  'Camera access was not granted. You can still choose a photo below.';

const DECODE_FAILURE = 'That file is not a readable image. Choose another.';

const PROCESS_FAILURE = 'Could not process that image. Try again.';

/**
 * Where this screen is between "never asked" and "the viewfinder is live."
 *
 * `'requesting'` exists only to disable the one button that can fire a second
 * concurrent `getUserMedia` call while the first is still resolving — nothing
 * else in the screen branches on it differently than `'unrequested'` does.
 */
type CameraState = 'unrequested' | 'requesting' | 'granted' | 'denied';

interface ScanScreenProps {
  /** Handed the downscaled Blob once either path produces one. */
  onCaptured: (image: Blob) => void;
  /** Discards nothing (no image is held here yet) and returns to the home panel. */
  onBack: () => void;
}

export function ScanScreen({ onCaptured, onBack }: ScanScreenProps): JSX.Element {
  const [cameraState, setCameraState] = useState<CameraState>('unrequested');
  const [fileError, setFileError] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Flips to `false` the instant this screen unmounts, so a `getUserMedia`
  // call already in flight at that moment knows, once it resolves, that
  // storing its stream and flipping state would both be pointless — nothing
  // is left to read either one.
  const mountedRef = useRef(true);
  const fileId = useId();

  /**
   * Stop every track the moment this screen leaves the document.
   *
   * A `MediaStream` keeps the camera's hardware light on until its tracks are
   * stopped explicitly — letting React garbage-collect the object does
   * nothing for the physical LED. This fires on Back to the home panel, on a
   * capture handing off to Crop, and on a sign-out, because all three unmount
   * this component the same way.
   */
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  /**
   * Bind the stream to the `<video>` element only once it exists.
   *
   * `<video>` renders exclusively in the `'granted'` branch below, so the
   * element is not yet mounted at the moment `enableCamera`'s `await`
   * resolves — assigning `srcObject` there would hit a still-`null` ref and
   * silently no-op. Running the assignment from an effect keyed on
   * `cameraState` guarantees it happens after the render that mounts the
   * element instead.
   */
  useEffect(() => {
    if (cameraState === 'granted' && videoRef.current !== null) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [cameraState]);

  async function enableCamera(): Promise<void> {
    setCameraState('requesting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
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
      setCameraState('granted');
    } catch {
      // Whatever the reason — denied, no camera present, an insecure origin —
      // the fallback is the same, and EXPERIENCE.md draws no distinction
      // between "denied" and "denied previously" either.
      setCameraState('denied');
    }
  }

  async function capture(): Promise<void> {
    const video = videoRef.current;
    if (video === null) return;
    // A tap that lands before the stream's first frame has decoded would
    // otherwise draw and encode a 0×0 canvas.
    if (video.videoWidth === 0 || video.videoHeight === 0) return;

    setFileError(null);
    setCapturing(true);
    try {
      const { width, height } = computeDownscaledDimensions(video.videoWidth, video.videoHeight);
      const blob = await downscaleToBlob(video, width, height);
      onCaptured(blob);
    } catch {
      setFileError(PROCESS_FAILURE);
    } finally {
      setCapturing(false);
    }
  }

  async function chooseFile(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    // Cleared unconditionally, and before the decode: a browser does not fire
    // `change` a second time for the same file re-chosen after a failure, so
    // the AC's "choose another file" would be unreachable for a retry of the
    // very file that just failed without this.
    if (fileInputRef.current !== null) fileInputRef.current.value = '';
    if (file === undefined) return;

    setFileError(null);
    let bitmap: ImageBitmap;
    try {
      // The browser's own decode, and the only check this screen makes on the
      // chosen file. No extension check, no MIME check — a `.tif` behind a
      // `.jpg` name is not pre-judged, and content is what decides.
      // `imageOrientation: 'from-image'` reads the file's own EXIF
      // orientation so a phone photo decodes upright consistently across
      // browsers, rather than however each one defaults.
      bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch {
      setFileError(DECODE_FAILURE);
      return;
    }
    try {
      const { width, height } = computeDownscaledDimensions(bitmap.width, bitmap.height);
      const blob = await downscaleToBlob(bitmap, width, height);
      onCaptured(blob);
    } catch {
      setFileError(PROCESS_FAILURE);
    } finally {
      bitmap.close();
    }
  }

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Scan</h1>

      <div className={styles.actions}>
        {/* Matches the Audit/Catalogue pattern: Back is the only control up
            here, and it is the navy outline, never in competition with the
            one accent control below. */}
        <button className={styles.back} type="button" onClick={onBack}>
          Back
        </button>
      </div>

      <div className={styles.viewfinder}>
        {cameraState === 'granted' ? (
          <>
            <video
              className={styles.video}
              ref={videoRef}
              autoPlay
              muted
              playsInline
              data-testid="viewfinder-video"
            />
            {/* Decorative only — see the module comment above. No blur or
                framing check runs against it; that is Story 3.3. */}
            <div
              className={styles.frameGuide}
              aria-hidden="true"
              data-testid="framing-guide-overlay"
            />
            <p className={styles.guideCopy}>Fill the frame with the tile face.</p>
          </>
        ) : cameraState === 'denied' ? (
          <p className={styles.denied}>{CAMERA_DENIED}</p>
        ) : (
          <div className={styles.explanation}>
            <p className={styles.lede}>{CAMERA_EXPLANATION}</p>
            <button
              className={styles.primary}
              type="button"
              onClick={() => void enableCamera()}
              disabled={cameraState === 'requesting'}
            >
              Enable camera
            </button>
          </div>
        )}
      </div>

      <div className={styles.controls}>
        {cameraState === 'granted' && (
          // The framing guide's shutter — DESIGN.md's Button (primary) reused
          // rather than a component of its own key-scan.html invents no token
          // for. Mutually exclusive with "Enable camera" above (never both
          // rendered at once), which is why the two share one accent rule in
          // the stylesheet rather than two.
          <button
            className={styles.primary}
            type="button"
            onClick={() => void capture()}
            disabled={capturing}
          >
            Capture
          </button>
        )}

        <div className={styles.uploadField}>
          {/* Left as the platform control rather than hidden behind a styled
              button — `AddTileScreen`'s own precedent: the native input is
              keyboard-reachable and announces the chosen file by itself. */}
          <label className={styles.uploadLabel} htmlFor={fileId}>
            Choose a photo
          </label>
          <input
            className={styles.fileInput}
            id={fileId}
            type="file"
            accept="image/*"
            ref={fileInputRef}
            onChange={(event) => void chooseFile(event)}
          />
        </div>
      </div>

      {fileError !== null && (
        <p className={styles.error} role="alert">
          {fileError}
        </p>
      )}
    </section>
  );
}
