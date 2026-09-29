import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { JSX, MouseEvent } from 'react';

import type { Marker, Measurement, Point } from '@rocell/schema/marker';

import {
  ApiRequestError,
  fetchScanMarkers,
  MARKER_NOT_DETECTED,
  measureTile,
} from '../api/client';
import styles from './MeasureScreen.module.css';

/**
 * Measure — how big the tile in the photo actually is.
 *
 * Size is the one attribute a photo cannot carry. Two tiles with the same
 * pattern at `45X90` and `60X30` are both 2:1 rectangles, so no amount of
 * shape reasoning separates them and the retrieval cannot either; only true
 * millimetres can. This screen gets them by comparing the tile against a
 * **Marker** — an object of known printed size lying on it — and the
 * homography between the marker's four corners and its known dimensions is
 * what turns every other pixel distance in the frame into millimetres.
 *
 * **The whole method rests on the marker lying flat on the tile.** A
 * homography maps one plane to another, so the two must be the same plane. A
 * card propped against something, or resting on the floor beside a tile held
 * upright, produces a confident and wrong answer — which is why the server
 * refuses a measurement whose rectified tile is not a rectangle, and why the
 * instruction below says "lying flat on the tile" rather than "in the photo".
 *
 * **The answer is a suggestion and this screen never applies it.** It hands
 * the matched Size back to `ScanScreen`, which pre-fills its picker with it;
 * the staff member can change it or clear it to All sizes before submitting.
 * AD-19 is why: a declared Size is a *hard* pre-filter, so a wrong one makes
 * the true Tile unreachable rather than merely lower-ranked, and no ranking
 * recovers from that. A measurement taken through a slipped marker is exactly
 * such a wrong one.
 *
 * **Two ways to find the marker, and the screen falls back by itself.** It
 * first asks the server to detect the Marker's printed fiducial. When that
 * comes back `marker_not_detected` — a creased card, a glare, a card outside
 * the frame, or a Marker with no fiducial at all — it asks for the marker's
 * four corners to be tapped and sends those instead. The staff member is never
 * asked to choose between the two up front, because they cannot know which
 * will work until one has failed.
 *
 * Rendered inside the shell, so it carries no `<main>` of its own and adds a
 * Back control that returns to Scan — which is where it was reached from.
 */

/** How many corners a quad has. Mirrors `shared_schema.marker.QUAD_CORNERS`. */
const QUAD_CORNERS = 4;

const TAP_THE_TILE = 'Tap the tile’s four corners, in any order.';
const TAP_THE_MARKER =
  'The marker was not found automatically. Tap the marker’s four corners too, in any order.';
const READY_TO_MEASURE = 'Ready. Measure, or tap again to start over.';
const NO_MARKERS =
  'No markers are registered, so there is nothing to measure against. An administrator ' +
  'registers one on the Markers screen.';
const COULD_NOT_MEASURE = 'The measurement could not be taken.';

interface MeasureScreenProps {
  /** The photo to measure — the whole frame, never the scan crop. */
  image: Blob;
  /**
   * Accept the measured Size. `ScanScreen` pre-fills its picker with it; the
   * staff member confirms or changes it before the scan is submitted.
   */
  onUseSize: (size: string) => void;
  /** Back to Scan without measuring. */
  onBack: () => void;
}

export function MeasureScreen({ image, onUseSize, onBack }: MeasureScreenProps): JSX.Element {
  const [markers, setMarkers] = useState<readonly Marker[] | null>(null);
  const [markerId, setMarkerId] = useState('');
  const [tileCorners, setTileCorners] = useState<readonly Point[]>([]);
  const [markerCorners, setMarkerCorners] = useState<readonly Point[]>([]);
  /**
   * Whether the marker's corners are being collected.
   *
   * Set only by a `marker_not_detected` refusal, never by the staff member:
   * they cannot know in advance whether the card will be found, and offering
   * the choice up front would make the automatic path something to opt into
   * rather than the default.
   */
  const [tapMarker, setTapMarker] = useState(false);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const markerFieldId = useId();
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  /**
   * The photo as something an `<img>` can show.
   *
   * Revoked on unmount: an object URL pins the Blob in memory until it is, and
   * this screen is reached from a flow that is already holding a full-size
   * photo.
   */
  const photoUrl = useMemo(() => URL.createObjectURL(image), [image]);
  useEffect(() => () => URL.revokeObjectURL(photoUrl), [photoUrl]);

  useEffect(() => {
    void fetchScanMarkers()
      .then((available) => {
        if (!mountedRef.current) return;
        setMarkers(available);
        // Pre-select when there is only one: picking from a list of one is a
        // tap that decides nothing.
        if (available.length > 0) setMarkerId(available[0]?.id ?? '');
      })
      .catch(() => {
        if (mountedRef.current) setMarkers([]);
      });
  }, []);

  /**
   * The Size this measurement supports, or `null`.
   *
   * Read into a local so the compiler can narrow it for the handler below —
   * `measurement.matched_size` is state, and TypeScript cannot prove a state
   * field is still non-null inside a closure that runs later.
   */
  const matchedSize = measurement?.matched_size ?? null;

  /** Which quad the next tap belongs to. */
  const collecting = tapMarker ? markerCorners : tileCorners;
  const complete = tapMarker
    ? markerCorners.length === QUAD_CORNERS && tileCorners.length === QUAD_CORNERS
    : tileCorners.length === QUAD_CORNERS;

  function instruction(): string {
    if (markers !== null && markers.length === 0) return NO_MARKERS;
    if (tapMarker && markerCorners.length < QUAD_CORNERS) return TAP_THE_MARKER;
    if (tileCorners.length < QUAD_CORNERS) return TAP_THE_TILE;
    return READY_TO_MEASURE;
  }

  /**
   * Record one tap, in normalized image coordinates.
   *
   * Normalized rather than absolute pixels, which is AD-11's rule for the scan
   * crop and holds for the same reason: this was tapped against a displayed
   * image whose on-screen size is a property of the phone, not of the upload.
   *
   * A fifth tap starts that quad over rather than being ignored. Ignoring it
   * would leave a staff member who mis-tapped with no way out but Back, and
   * the corners are cheap to re-collect.
   */
  function tap(event: MouseEvent<HTMLButtonElement>): void {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width === 0 || bounds.height === 0) return;
    const point = {
      x: (event.clientX - bounds.left) / bounds.width,
      y: (event.clientY - bounds.top) / bounds.height,
    };
    const next = collecting.length >= QUAD_CORNERS ? [point] : [...collecting, point];
    if (tapMarker) setMarkerCorners(next);
    else setTileCorners(next);
    setMeasurement(null);
  }

  async function measure(): Promise<void> {
    setBusy(true);
    setFailure(null);
    try {
      const answer = await measureTile(
        image,
        markerId,
        tileCorners,
        // Present only once the automatic path has actually failed — their
        // presence is what selects the manual path server-side.
        tapMarker ? markerCorners : null,
      );
      if (!mountedRef.current) return;
      setMeasurement(answer);
      setBusy(false);
    } catch (error) {
      if (!mountedRef.current) return;
      setBusy(false);
      if (error instanceof ApiRequestError && error.code === MARKER_NOT_DETECTED) {
        // Not a failure to report and stop on — it is the signal to collect
        // the corners by hand. The API's sentence says so, so it is rendered
        // as the instruction rather than as a rejection.
        setTapMarker(true);
        setMarkerCorners([]);
        return;
      }
      setFailure(error instanceof ApiRequestError ? error.message : COULD_NOT_MEASURE);
    }
  }

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Measure the tile</h1>

      <div className={styles.field}>
        <label className={styles.label} htmlFor={markerFieldId}>
          Marker
        </label>
        <select
          className={styles.select}
          id={markerFieldId}
          value={markerId}
          disabled={markers === null || markers.length === 0}
          onChange={(event) => {
            setMarkerId(event.target.value);
            // A different ruler invalidates everything measured with the last
            // one, including the fallback decision.
            setMeasurement(null);
            setTapMarker(false);
            setMarkerCorners([]);
          }}
        >
          {(markers ?? []).map((marker) => (
            <option key={marker.id} value={marker.id}>
              {marker.name} ({marker.width_mm} × {marker.height_mm} mm)
            </option>
          ))}
        </select>
      </div>

      <p className={styles.instruction}>{instruction()}</p>

      <button className={styles.canvas} type="button" onClick={tap}>
        <img className={styles.photo} src={photoUrl} alt="The tile being measured" />
        {tileCorners.map((corner, index) => (
          <span
            className={styles.corner}
            // Corners have no identity of their own and are only ever appended
            // or cleared as a set, so the position is the key.
            key={`tile-${String(index)}`}
            style={{ left: `${String(corner.x * 100)}%`, top: `${String(corner.y * 100)}%` }}
          />
        ))}
        {markerCorners.map((corner, index) => (
          <span
            className={styles.markerCorner}
            key={`marker-${String(index)}`}
            style={{ left: `${String(corner.x * 100)}%`, top: `${String(corner.y * 100)}%` }}
          />
        ))}
      </button>

      {failure !== null && (
        <p className={styles.failure} role="alert">
          {failure}
        </p>
      )}

      {measurement !== null && (
        <div className={styles.result}>
          <span className={styles.millimetres}>
            {Math.round(measurement.short_mm)} × {Math.round(measurement.long_mm)} mm
          </span>
          <span className={styles.matched}>
            {measurement.matched_size === null
              ? 'No catalogue size matches this measurement'
              : `Matches ${measurement.matched_size}`}
          </span>
          <span className={styles.method}>
            {measurement.auto_detected
              ? 'Marker found automatically.'
              : 'Measured from the corners you tapped.'}
          </span>
        </div>
      )}

      <div className={styles.actions}>
        {matchedSize === null ? (
          <button
            className={styles.measure}
            type="button"
            disabled={busy || !complete || markerId === ''}
            onClick={() => void measure()}
          >
            {busy ? 'Measuring…' : 'Measure'}
          </button>
        ) : (
          // Once there is a Size, taking it to the scan is the primary act —
          // and the only accent control on the screen, so the two never
          // compete for the one orange action DESIGN.md allows.
          <button
            className={styles.measure}
            type="button"
            onClick={() => onUseSize(matchedSize)}
          >
            Use {matchedSize}
          </button>
        )}
        <button className={styles.back} type="button" onClick={onBack} disabled={busy}>
          Back
        </button>
      </div>
    </section>
  );
}
