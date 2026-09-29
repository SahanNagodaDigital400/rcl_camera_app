import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';

import { isMarker } from '@rocell/schema/marker';
import type { Marker } from '@rocell/schema/marker';

import { ApiRequestError, apiRequest, MALFORMED_RESPONSE } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';
import styles from './MarkerListScreen.module.css';

/**
 * Markers — the physical scale references a measurement can be taken with.
 *
 * A **Marker** is an object of known printed size (a fiducial card, an ID
 * badge, a bank card) that a staff member lays on a tile before photographing
 * it. The Measure flow finds its corners in the frame, and the known
 * millimetres between them are what turn the tile's pixels into a physical
 * size — which is the one attribute a photo genuinely cannot carry.
 *
 * **Administrator-only, and that is the whole control on this feature.** The
 * dimensions typed on the form behind "Register a marker" scale every
 * measurement every staff member takes with that card. A `54mm` typed as
 * `540mm` produces confident answers wrong by a factor of ten, and nothing
 * downstream can see it: the geometry is valid, the tile rectifies as a
 * rectangle, and only the millimetres are absurd. One person holding the
 * printed card, typing what is on it, with an audit entry naming them, is what
 * stands between that and the catalogue. The server refuses a Staff caller at
 * every `/admin/markers` route regardless of what this renders.
 *
 * **Not part of the Catalogue, and deliberately not reached through it.** A
 * Marker names no Tile, no Size and no Category — it is a ruler that happens
 * to live in the same database. It is reached from the home panel's quick
 * links, beside "Manage users", because that is the shape of the thing it is:
 * an administrative register, not a view of the catalogue.
 *
 * Rendered inside the shell, so it carries no `<main>` of its own and adds a
 * Back control that returns to the home panel — which is where it was pressed.
 */

/** What the list says when nothing has been registered yet. */
const NOTHING_REGISTERED =
  'No markers are registered. Until one is, the Scan screen offers no Measure control and ' +
  'staff declare the size themselves.';

/** The failure a read can end in, in the product's own voice. */
const COULD_NOT_LOAD = 'The markers could not be loaded.';

interface MarkerListScreenProps {
  /** Back to the home panel — where this screen was reached from. */
  onBack: () => void;
  /** Open the registration form. */
  onAdd: () => void;
  /** Open the correction form for one Marker. */
  onEdit: (marker: Marker) => void;
}

/**
 * Narrow a response body to `Marker[]`.
 *
 * Defined here rather than imported, which is `UserListScreen.asUsers`'s own
 * arrangement: the narrowing belongs to the screen that has to decide what to
 * render when it fails. A Marker carrying half a fiducial declaration, or a
 * `NaN` dimension, is a malformed response rather than a row that renders a
 * ruler nobody can measure with.
 */
function asMarkers(body: unknown): readonly Marker[] {
  if (Array.isArray(body) && body.every(isMarker)) return body as Marker[];
  throw new ApiRequestError(MALFORMED_RESPONSE, COULD_NOT_LOAD, 200);
}

/**
 * Read the register.
 *
 * Module-level rather than a `useCallback`, and that is what keeps both of
 * `oxlint`'s effect rules satisfied at once: it closes over no state, so the
 * mount effect can list no dependencies at all, and the removal path can call
 * the same function without the effect gaining a dependency it does not use.
 */
async function readMarkers(): Promise<readonly Marker[]> {
  return asMarkers(await apiRequest('/admin/markers'));
}

/**
 * The printed dimensions as one readable string.
 *
 * `×` rather than `x`, and millimetres named rather than assumed: this is read
 * against a card in somebody's hand, and "85.6 × 54" with no unit is the kind
 * of thing that gets retyped into a field expecting centimetres.
 */
function dimensions(marker: Marker): string {
  return `${marker.width_mm} × ${marker.height_mm} mm`;
}

/**
 * How this Marker is found in a photo.
 *
 * Stated on every row, including the plain ones. "Nothing here" on a row that
 * carries no fiducial would read as a value that failed to load rather than as
 * the ordinary, supported case it is.
 */
function detection(marker: Marker): string {
  if (marker.aruco_dictionary === null || marker.aruco_id === null) {
    return 'Tapped corners — no printed fiducial';
  }
  return `Detected automatically — ${marker.aruco_dictionary}, id ${marker.aruco_id}`;
}

export function MarkerListScreen({ onBack, onAdd, onEdit }: MarkerListScreenProps): JSX.Element {
  const [markers, setMarkers] = useState<readonly Marker[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Marker | null>(null);
  const [busy, setBusy] = useState(false);

  /**
   * Whether this screen is still mounted.
   *
   * Every other screen in the product keeps one: a response that lands after
   * the Administrator has moved on would otherwise set state on an unmounted
   * tree, and on the removal path it would also reopen a dialog they closed.
   */
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // `ScanScreen`'s shape: a promise chain rather than an awaited call, so
  // nothing in the effect body writes state synchronously.
  useEffect(() => {
    void readMarkers()
      .then((rows) => {
        if (!mountedRef.current) return;
        setMarkers(rows);
        setFailure(null);
      })
      .catch((error: unknown) => {
        if (!mountedRef.current) return;
        // The API's own sentence wherever there is one (EXPERIENCE.md:87) —
        // this screen never composes its own version of a rule it does not own.
        setFailure(error instanceof ApiRequestError ? error.message : COULD_NOT_LOAD);
        setMarkers([]);
      });
  }, []);

  async function confirmRemoval(): Promise<void> {
    if (removing === null) return;
    setBusy(true);
    try {
      await apiRequest(`/admin/markers/${removing.id}`, { method: 'DELETE' });
      if (!mountedRef.current) return;
      setRemoving(null);
      setBusy(false);
      // Re-read here rather than through the effect: the removal is the event
      // that changed the list, and an effect re-firing on a counter would be a
      // second write path to the same state.
      const rows = await readMarkers();
      if (mountedRef.current) setMarkers(rows);
    } catch (error) {
      if (!mountedRef.current) return;
      setBusy(false);
      setRemoving(null);
      setFailure(error instanceof ApiRequestError ? error.message : COULD_NOT_LOAD);
    }
  }

  return (
    <section className={styles.screen}>
      <div className={styles.header}>
        <h1 className={styles.title}>Markers</h1>
        <div className={styles.actions}>
          <button className={styles.add} type="button" onClick={onAdd}>
            Register a marker
          </button>
          <button className={styles.back} type="button" onClick={onBack}>
            Back
          </button>
        </div>
      </div>

      <p className={styles.intro}>
        A marker is an object of known size laid on a tile before it is photographed, so a scan can
        measure the tile. Measure the printed black square itself, not the paper around it, and type
        the size in millimetres. Tell staff to place it near a corner of the tile — a marker in the
        middle costs about 17 points of matching accuracy, and one in a corner costs nothing.
      </p>

      {failure !== null && (
        <p className={styles.failure} role="alert">
          {failure}
        </p>
      )}

      {markers === null && <p className={styles.loading}>Loading markers…</p>}

      {markers !== null && markers.length === 0 && failure === null && (
        <p className={styles.empty}>{NOTHING_REGISTERED}</p>
      )}

      {markers !== null && markers.length > 0 && (
        <ul className={styles.list}>
          {markers.map((marker) => (
            <li className={styles.row} key={marker.id}>
              <div className={styles.rowMain}>
                <span className={styles.name}>{marker.name}</span>
                <span className={styles.dimensions}>{dimensions(marker)}</span>
                <span className={styles.fiducial}>{detection(marker)}</span>
              </div>
              <div className={styles.rowActions}>
                <button className={styles.edit} type="button" onClick={() => onEdit(marker)}>
                  Edit {marker.name}
                </button>
                <button
                  className={styles.remove}
                  type="button"
                  onClick={() => setRemoving(marker)}
                >
                  Remove {marker.name}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {removing !== null && (
        <ConfirmDialog
          kind="confirm"
          heading="Remove this marker?"
          // Who this is about and what happens to them (EXPERIENCE.md:72).
          // The second sentence is the one that matters: removing a ruler
          // changes no past scan, because a measurement is a suggestion that
          // pre-fills the Size picker and is never stored.
          body={
            `${removing.name} (${dimensions(removing)}) will no longer be offered when staff ` +
            'measure a tile. No scan or catalogue entry is affected.'
          }
          confirmLabel="Remove"
          busy={busy}
          onConfirm={() => void confirmRemoval()}
          onClose={() => {
            if (!busy) setRemoving(null);
          }}
        />
      )}
    </section>
  );
}
