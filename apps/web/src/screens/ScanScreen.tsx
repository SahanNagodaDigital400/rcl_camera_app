import { ArrowsClockwise, Camera, Crop, Image, X } from '@phosphor-icons/react';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { ChangeEvent, JSX } from 'react';

import { ApiRequestError, fetchScanSizes, SCAN_QUALITY_TOO_LOW, UNKNOWN_SIZE } from '../api/client';
import {
  computeCentreSquare,
  computeDownscaledDimensions,
  downscaleToBlob,
} from '../scan/downscaleImage';
import styles from './ScanScreen.module.css';

/**
 * Scan — the entry point to the match pipeline, and the default landing
 * surface (EXPERIENCE.md Information Architecture).
 *
 * **One tap from a live viewfinder to a ranked answer.** A capture (the
 * centre square of the camera frame), or a chosen file (whole), is
 * downscaled and handed to `onCaptured`, which submits it for matching and
 * moves to Results when the answer lands. There
 * is no mandatory crop step in between: cropping is an *option* — offered on
 * Results ("Adjust crop") and here after a refusal ("Crop this photo") —
 * never a gate the staff member has to clear on every scan.
 *
 * **The camera starts by itself once it has been allowed before.** On
 * arrival the screen asks the Permissions API whether camera access is
 * already granted; if it is, the viewfinder opens without a tap — on every
 * visit, including the return from Results. If the browser would still have
 * to prompt (or cannot say), the screen explains why the camera is wanted
 * and waits for a tap, so the browser's own prompt never fires unannounced
 * (EXPERIENCE.md's "Camera permission not yet granted" state). Nothing is
 * written to storage for this: the browser's own permission record is the
 * source of truth, and `no-client-token-storage.test.ts` keeps page script
 * away from `localStorage` for the session's sake.
 *
 * **"Choose a photo" is never gated on the camera.** It renders in every
 * state — before a request, while one is in flight, after a grant, after a
 * denial — because EXPERIENCE.md's Accessibility Floor treats camera denial
 * as a state with a first-class fallback, never a dead end. It sits in the
 * controls row overlaid on the viewfinder at every state, so it is always in
 * the same place under the thumb (`mockups/key-scan.html`).
 *
 * **Every banner can be dismissed.** A refusal and a failure both sit over
 * the viewfinder, above the shutter, where they cannot be missed — which is
 * also where they would be in the way once read. Each carries a labelled
 * close control, and taking another photo clears them anyway, so the live
 * feed is never blocked by a message the staff member has finished with.
 *
 * **The shutter submits the centre square of the camera frame** —
 * `computeCentreSquare`, which is the POC's own capture
 * (`poc/tilematch/web/index.html`: `side = Math.min(vw, vh)`, taken from the
 * middle) transcribed. The square viewfinder shows exactly that region under
 * `object-fit: cover`, so the accent outline is a framing aid around what is
 * genuinely being matched rather than a second, smaller crop inside it.
 *
 * **This deliberately replaced a guide-shaped crop, and the reason is
 * accuracy.** The outline used to be inset on all four edges and *that*
 * region was what got submitted — a fraction of the frame, where the POC
 * sends the whole centre square. Nothing in `shared/vision` differed between
 * the two systems (the active generation's `config_hash` is identical to the
 * POC index's), so the framing was the difference. Narrowing it again, here
 * or in the stylesheet, re-opens the same gap and will not fail a test that
 * is not looking for it.
 *
 * It remains a framing aid, not a gate: nothing is rejected for sitting
 * outside the outline, and the quality check still runs server-side on
 * whatever region arrives.
 *
 * **Only the capture path is squared off.** A chosen file was framed
 * somewhere else entirely — the POC leaves the file picker uncropped for that
 * same reason — so "Choose a photo" submits the whole image and the optional
 * crop editor is how a staff member narrows it.
 *
 * **Content decides, never the extension** — `AddTileScreen`'s own rule,
 * applied here to the file picker: `accept="image/*"` is a hint to the
 * picker, not a check, and only a genuine decode failure (`createImageBitmap`
 * rejecting) produces the inline error.
 *
 * **The native file input stays the control.** It is visually hidden, not
 * removed: the styled label is what the eye sees and taps, the input is what
 * the keyboard reaches and what announces the chosen file, and `label[for]`
 * is what joins them — so no click handler re-implements the picker.
 */

const CAMERA_EXPLANATION =
  'Rocell Tile Scanner needs your camera to photograph a tile. Nothing is captured until you tap the shutter.';

const CAMERA_DENIED = 'Camera access was not granted. You can still choose a photo below.';

const CAMERA_STARTING = 'Starting the camera…';

const CAMERA_CHECKING = 'Checking the camera…';

const DECODE_FAILURE = 'That file is not a readable image. Choose another.';

const PROCESS_FAILURE = 'Could not process that image. Try again.';

const SUBMIT_FAILURE = 'Could not submit the scan. Try again.';

const MATCHING = 'Matching…';

/**
 * Whether the Permissions API is there to be asked. Decided synchronously so
 * the first render already knows whether to show the explanation or a short
 * "checking" wait — no flash of one before the other.
 */
function canQueryPermission(): boolean {
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

/**
 * Where this screen is between "never asked" and "the viewfinder is live."
 *
 * `'checking'` is the arrival wait while the Permissions API answers;
 * `'starting'` is the already-granted case, the request being made on
 * arrival — neither flashes the explanation before the viewfinder.
 * `'requesting'` is the same wait after a tap, and disables the one button
 * that could fire a second concurrent `getUserMedia` call while the first is
 * resolving.
 */
type CameraState = 'unrequested' | 'checking' | 'starting' | 'requesting' | 'granted' | 'denied';

/** The picker's "declare nothing" option. Not a Size, so it is not a string. */
export const ALL_SIZES = '';

interface ScanScreenProps {
  /**
   * Submit the downscaled frame for matching. Resolves once Results is
   * showing (which unmounts this screen); rejects with the `ApiRequestError`
   * the request produced, which this screen renders in place.
   */
  onCaptured: (image: Blob) => Promise<void>;
  /** Open the optional crop editor on the frame just captured. */
  onCrop: (image: Blob) => void;
  /**
   * The Size the next scan declares, or `null` for "All sizes".
   *
   * **Held by `App`, not by this screen, and deliberately not by the
   * browser.** The POC remembers the choice in `localStorage` between scans;
   * `no-client-token-storage.test.ts` forbids browser storage anywhere in
   * this app — explicitly including "just a UI preference", because a rule
   * with that exception is one the next person reads as negotiable. Lifting
   * it to `App` gets the behaviour that matters: a staff member working
   * through a pallet of one size sets it once and it survives every
   * Scan → Results → Scan round trip. It resets on a reload, which is the
   * price of the storage rule and is worth saying out loud.
   */
  declaredSize: string | null;
  /** Record a new declaration. `null` is "All sizes". */
  onDeclareSize: (size: string | null) => void;
}

/**
 * No Back control: Scan is the landing surface, the nav reaches everything
 * else, and a control that leads "back" from the place a shift starts is one
 * more thing on a phone screen whose whole job is the viewfinder.
 */
export function ScanScreen({
  onCaptured,
  onCrop,
  declaredSize,
  onDeclareSize,
}: ScanScreenProps): JSX.Element {
  const [cameraState, setCameraState] = useState<CameraState>(() =>
    canQueryPermission() ? 'checking' : 'unrequested',
  );
  const [fileError, setFileError] = useState<string | null>(null);
  /** The server's quality refusal for the last submission, or `null`. */
  const [qualityRefusal, setQualityRefusal] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  /** The last frame submitted, kept for "Try again" and "Crop this photo". */
  const [lastImage, setLastImage] = useState<Blob | null>(null);
  /**
   * The Sizes this catalogue can be asked about, commonest first.
   *
   * Empty until the read resolves, and empty for good on a catalogue that has
   * never been indexed or a read that failed — in all three cases the picker
   * simply does not render. A failure is deliberately silent: the size filter
   * is an accuracy *option*, and a banner about it over a live viewfinder
   * would be in the way of the one thing this screen is for.
   */
  const [sizes, setSizes] = useState<readonly string[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // `true` while this screen is in the document, so a `getUserMedia` call
  // still in flight when it leaves knows, once it resolves, that storing its
  // stream and flipping state would both be pointless.
  const mountedRef = useRef(true);
  // One camera request at a time: StrictMode runs the mount effect twice and
  // a fast double tap fires the button twice, and either would otherwise open
  // two streams and keep the hardware light on for the one nobody holds.
  const requestingRef = useRef(false);
  const fileId = useId();
  const sizeId = useId();
  const sizeHintId = useId();

  /**
   * Ask the browser for the rear camera, and remember the answer.
   *
   * Called from exactly two places: the "Enable camera" tap on a first visit
   * (via `enableCamera`, which also shows the wait), and the mount effect
   * below once the Permissions API has said access is already granted. Never
   * from anywhere else, so the explanation always precedes the browser's own
   * prompt the first time it can appear.
   */
  const requestCamera = useCallback(async (): Promise<void> => {
    if (requestingRef.current) return;
    requestingRef.current = true;
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
      if (mountedRef.current) setCameraState('denied');
    } finally {
      requestingRef.current = false;
    }
  }, []);

  /** The first-visit tap: show the wait, then ask. */
  function enableCamera(): void {
    setCameraState('requesting');
    void requestCamera();
  }

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
   * handing off to Results, and on a sign-out, because all three unmount
   * this component the same way.
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
   * Read the Sizes this catalogue can be filtered by, once, on arrival.
   *
   * `mountedRef` is checked in the `then`, `requestCamera`'s own reason: the
   * screen can be left while the request is in flight, and setting state
   * afterward would be a warning for a picker nobody is looking at.
   *
   * A rejection leaves `sizes` empty and renders no picker — see its own
   * declaration above. `void` rather than a floating promise so the intent is
   * explicit: nothing downstream waits for this, and the viewfinder must not.
   */
  useEffect(() => {
    void fetchScanSizes()
      .then((available) => {
        if (mountedRef.current) setSizes(available);
      })
      .catch(() => {
        // Deliberately swallowed. See `sizes`.
      });
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

  /**
   * Submit one frame. On success `App` moves to Results and this screen
   * unmounts, so nothing is set after the `await`; a refusal is rendered in
   * place, with the viewfinder still live for the next attempt.
   */
  /**
   * A declaration the catalogue has since stopped recognising.
   *
   * Only reachable when the catalogue changed under a screen already open, so
   * the recovery is to re-read the list and drop the stale choice rather than
   * to ask the staff member to fix something they did not get wrong. The
   * photo is still in `lastImage`, so the next tap re-submits it against
   * every size.
   */
  function forgetStaleSize(): void {
    onDeclareSize(null);
    void fetchScanSizes()
      .then((available) => {
        if (mountedRef.current) setSizes(available);
      })
      .catch(() => {
        // See `sizes`.
      });
  }

  async function submit(image: Blob): Promise<void> {
    setLastImage(image);
    setFileError(null);
    setQualityRefusal(null);
    setSubmitting(true);
    try {
      await onCaptured(image);
    } catch (failure) {
      if (failure instanceof ApiRequestError && failure.code === SCAN_QUALITY_TOO_LOW) {
        // The photo's content failed, not the request: the answer is another
        // photo (the shutter is right there) or, if the tile is small in the
        // frame, a crop of this one.
        setQualityRefusal(failure.message);
      } else if (failure instanceof ApiRequestError && failure.code === UNKNOWN_SIZE) {
        forgetStaleSize();
        setFileError(failure.message);
      } else {
        setFileError(failure instanceof ApiRequestError ? failure.message : SUBMIT_FAILURE);
      }
      setSubmitting(false);
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
    let blob: Blob;
    try {
      // The POC's capture: the centre square of the camera's short edge, read
      // straight from the frame's own dimensions rather than from a measured
      // overlay. Deterministic — there is no layout to get wrong and no
      // fallback path that submits a different region than the one on screen.
      const captured = computeCentreSquare(video.videoWidth, video.videoHeight);
      const { width, height } = computeDownscaledDimensions(captured.width, captured.height);
      blob = await downscaleToBlob(video, width, height, captured);
    } catch {
      setFileError(PROCESS_FAILURE);
      return;
    } finally {
      setCapturing(false);
    }
    await submit(blob);
  }

  async function chooseFile(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    // Cleared unconditionally, and before the decode: a browser does not fire
    // `change` a second time for the same file re-chosen after a failure, so
    // "choose another file" would be unreachable for a retry of the very file
    // that just failed without this.
    if (fileInputRef.current !== null) fileInputRef.current.value = '';
    if (file === undefined) return;

    setFileError(null);
    let bitmap: ImageBitmap;
    try {
      // The browser's own decode, and the only check this screen makes on the
      // chosen file. `imageOrientation: 'from-image'` reads the file's own
      // EXIF orientation so a phone photo decodes upright consistently across
      // browsers, rather than however each one defaults.
      bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch {
      setFileError(DECODE_FAILURE);
      return;
    }
    let blob: Blob;
    try {
      const { width, height } = computeDownscaledDimensions(bitmap.width, bitmap.height);
      blob = await downscaleToBlob(bitmap, width, height);
    } catch {
      setFileError(PROCESS_FAILURE);
      return;
    } finally {
      bitmap.close();
    }
    await submit(blob);
  }

  /** Put the viewfinder back: a message that has been read is in the way. */
  function dismiss(): void {
    setQualityRefusal(null);
    setFileError(null);
  }

  const busy = capturing || submitting;

  return (
    <section className={styles.screen}>
      {/* Spoken, and shown from the breakpoint up; on a phone the tab bar
          already says where we are and every row belongs to the camera. */}
      <h1 className={styles.title}>Scan</h1>

      {/* The camera surface — full-bleed on a phone, a framed panel from the
          breakpoint up. The controls row is overlaid on its bottom edge at
          every state, so "Choose a photo" and the shutter are always in the
          same place under the thumb. */}
      <div className={styles.viewfinder} aria-busy={busy}>
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
            {/* The region the shutter captures — the whole square stage, see
                the module comment above. Still `aria-hidden`: it is a line on
                the video, and the sentence below it is what says what to do
                with it. */}
            <div
              className={styles.frameGuide}
              aria-hidden="true"
              data-testid="framing-guide-overlay"
            />
            <p className={styles.guideCopy}>Fill the box with the tile face.</p>
          </>
        ) : cameraState === 'denied' ? (
          <p className={styles.denied}>{CAMERA_DENIED}</p>
        ) : cameraState === 'checking' || cameraState === 'starting' ? (
          // The arrival wait: the browser is being asked whether access is
          // already granted, or the viewfinder is about to open on a grant it
          // confirmed. Neither re-explains a permission already given.
          <p className={styles.denied} role="status">
            {cameraState === 'checking' ? CAMERA_CHECKING : CAMERA_STARTING}
          </p>
        ) : (
          <div className={styles.explanation}>
            <Camera className={styles.explanationIcon} aria-hidden="true" />
            <p className={styles.lede}>{CAMERA_EXPLANATION}</p>
            <button
              className={styles.primary}
              type="button"
              onClick={enableCamera}
              disabled={cameraState === 'requesting'}
            >
              Enable camera
            </button>
          </div>
        )}

        {/* EXPERIENCE.md's "processing: lightweight spinner, not a skeleton".
            Overlaid on the viewfinder so the frame just captured is what the
            wait is visibly about, and announced once as a status. */}
        {submitting && (
          <div className={styles.busy} role="status">
            <span className={styles.spinner} aria-hidden="true" />
            <span className={styles.busyText}>{MATCHING}</span>
          </div>
        )}

        {/* Three columns, not `space-between`: the shutter stays optically
            centred and the fallback can never collide with it, whatever the
            label's rendered width (`mockups/key-scan.html`). */}
        <div className={styles.controls}>
          <div className={styles.uploadField}>
            <label className={styles.uploadLabel} htmlFor={fileId}>
              <Image className={styles.uploadIcon} aria-hidden="true" />
              Choose a photo
            </label>
            <input
              className={styles.fileInput}
              id={fileId}
              type="file"
              accept="image/*"
              ref={fileInputRef}
              disabled={submitting}
              onChange={(event) => void chooseFile(event)}
            />
          </div>

          {cameraState === 'granted' && (
            // The shutter — DESIGN.md's Button (primary) in the mockup's
            // square, with the word visually hidden and the glyph doing the
            // pointing. Mutually exclusive with "Enable camera" above (never
            // both rendered at once), which is why the two share one accent
            // rule in the stylesheet rather than two.
            <button
              className={`${styles.primary} ${styles.shutter}`}
              type="button"
              onClick={() => void capture()}
              disabled={busy}
            >
              <Camera className={styles.shutterIcon} aria-hidden="true" />
              <span className={styles.shutterLabel}>Capture</span>
            </button>
          )}

          <div className={styles.controlsSpacer} aria-hidden="true" />
        </div>

        {/* EXPERIENCE.md's `retake-prompt`: an inline, surface-coloured banner,
              never a modal — and never the destructive red, since a quality gate
              is not a failed request. Laid over the viewfinder directly above
              the shutter, where the eye already is, rather than below the camera
              where a message can scroll out of sight. The shutter is the retake;
              the one control here is the other way out, a crop of the frame that
              failed. */}
        {qualityRefusal !== null && lastImage !== null && (
          <div className={styles.prompt}>
            <div className={styles.promptHead}>
              <p className={styles.promptText} role="alert">
                {qualityRefusal}
              </p>
              {/* Labelled for assistive technology, an X to the eye — the
                  banner's own text is what a screen reader has already
                  announced, so the glyph carries no second sentence. */}
              <button
                aria-label="Dismiss"
                className={styles.dismiss}
                type="button"
                onClick={dismiss}
              >
                <X className={styles.dismissIcon} aria-hidden="true" />
              </button>
            </div>
            <div className={styles.promptActions}>
              <button className={styles.secondary} type="button" onClick={() => onCrop(lastImage)}>
                <Crop className={styles.secondaryIcon} aria-hidden="true" />
                Crop this photo
              </button>
            </div>
          </div>
        )}

        {/* A decode or submission failure, in the same place for the same
              reason. Red is destructive-or-failed in this system and nothing
              else, and it is never the only signal: the text says what happened,
              and the way forward sits beside it. */}
        {fileError !== null && (
          <div className={styles.failure}>
            <div className={styles.promptHead}>
              <p className={styles.error} role="alert">
                {fileError}
              </p>
              <button
                aria-label="Dismiss"
                className={styles.dismiss}
                type="button"
                onClick={dismiss}
              >
                <X className={styles.dismissIcon} aria-hidden="true" />
              </button>
            </div>
            {lastImage !== null && (
              <div className={styles.promptActions}>
                <button
                  className={styles.secondary}
                  type="button"
                  disabled={submitting}
                  onClick={() => void submit(lastImage)}
                >
                  <ArrowsClockwise className={styles.secondaryIcon} aria-hidden="true" />
                  Try again
                </button>
                <button
                  className={styles.secondary}
                  type="button"
                  onClick={() => onCrop(lastImage)}
                >
                  <Crop className={styles.secondaryIcon} aria-hidden="true" />
                  Crop this photo
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* The size declaration — on the capture screen rather than in a
          settings page, the POC's own placement and for its reason: it is the
          one attribute a photo cannot carry and the person holding the tile
          always knows, so it is answered where the tile is being photographed.

          **A sibling of the viewfinder, never a child of it.** Everything
          inside that element is absolutely positioned over the camera feed —
          the guide, the copy, the spinner, the controls row — so a field box
          placed there renders as an opaque card on top of the live picture.
          It belongs under the stage, in the screen's own column flow.

          Rendered only when the catalogue has sizes to offer.

          **Defaults to All sizes and is never guessed.** A *mis*-declared
          size makes the true tile unreachable — no amount of ranking
          recovers from it — so the cost of a wrong declaration is higher
          than the gain from a right one, and the hint says to leave it
          alone when unsure. */}
      {sizes.length > 0 && (
        <div className={styles.sizeField}>
          <label className={styles.sizeLabel} htmlFor={sizeId}>
            Tile size
          </label>
          {/* The hint below is bound to this control — `AddTileScreen`'s own
              rule, and it earns it here: the sentence carries the *cost* of
              declaring a size, which is stated nowhere else. A screen-reader
              user who never reaches that paragraph would otherwise meet it
              as a scan that quietly could not find the tile. */}
          <select
            className={styles.sizeSelect}
            id={sizeId}
            value={declaredSize ?? ALL_SIZES}
            disabled={busy}
            aria-describedby={sizeHintId}
            onChange={(event) =>
              onDeclareSize(event.target.value === ALL_SIZES ? null : event.target.value)
            }
          >
            <option value={ALL_SIZES}>All sizes</option>
            {sizes.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
          <p className={styles.sizeHint} id={sizeHintId}>
            Narrows the search when you know the size. Leave on All sizes if unsure — a wrong size
            hides the right tile.
          </p>
        </div>
      )}
    </section>
  );
}
