import { useId, useState } from 'react';
import type { FormEvent, JSX } from 'react';

import { ARUCO_DICTIONARIES, ARUCO_DICTIONARY_SIZES, isMarker } from '@rocell/schema/marker';
import type { ArucoDictionary, Marker } from '@rocell/schema/marker';

import { ApiRequestError, apiRequest, MALFORMED_RESPONSE } from '../api/client';
import styles from './MarkerFormScreen.module.css';

/**
 * Register a marker, or correct one — the form behind the Markers screen.
 *
 * **One screen for both, unlike Create user and Edit user.** Those are two
 * screens because they take different fields: the create path issues a
 * temporary credential and the edit path has no password at all. This form
 * takes exactly the same four things either way, and splitting it would be two
 * copies of one set of bounds, drifting.
 *
 * **The dimensions are the dangerous field, and the hint under them is the
 * control.** They scale every measurement taken with the card. Measuring the
 * paper rather than the printed black square inflates every result by the
 * quiet zone's width — a real, silent, roughly 10–20% error — and typing
 * centimetres into a millimetre field is out by ten. Neither fails anywhere a
 * reader can see: the geometry stays valid and the tile still rectifies as a
 * rectangle. Only the millimetres are absurd.
 *
 * **The server's copy is the authority** — `shared_schema.marker` bounds all
 * four fields and `apps/api/api/markers.py` refuses anything outside them.
 * The bounds mirrored here refuse the same input one step earlier, so an
 * Administrator is corrected while looking at the field rather than after a
 * round trip; `error-code-parity.test.ts` pins the two together.
 *
 * Rendered inside the shell, so it carries no `<main>` of its own and adds a
 * Back control that returns to the Markers list.
 */

/**
 * The name bound, mirroring `shared_schema.marker.MAX_MARKER_NAME_LENGTH`.
 *
 * A literal rather than an import, which is `AddTileScreen`'s arrangement:
 * `error-code-parity.test.ts` reads this line as an integer and compares it
 * against the Python constant, and an expression would make that comparison
 * compare against nothing.
 */
const MAX_MARKER_NAME_LENGTH = 200;

/** `shared_schema.marker.MIN_MARKER_EDGE_MM` / `MAX_MARKER_EDGE_MM`, mirrored. */
const MIN_MARKER_EDGE_MM = 20;
const MAX_MARKER_EDGE_MM = 1000;

/** The picker's "no printed fiducial" option. Not a dictionary, so not a string. */
const NO_FIDUCIAL = '';

const COULD_NOT_SAVE = 'The marker could not be saved.';

interface MarkerFormScreenProps {
  /** The Marker being corrected, or `null` to register a new one. */
  marker: Marker | null;
  /** Saved — back to the list, which reloads. */
  onSaved: () => void;
  /** Back to the list without writing. */
  onCancel: () => void;
}

function asMarker(body: unknown): Marker {
  if (isMarker(body)) return body;
  throw new ApiRequestError(MALFORMED_RESPONSE, COULD_NOT_SAVE, 200);
}

export function MarkerFormScreen({
  marker,
  onSaved,
  onCancel,
}: MarkerFormScreenProps): JSX.Element {
  const editing = marker !== null;

  const [name, setName] = useState(marker?.name ?? '');
  const [width, setWidth] = useState(marker === null ? '' : String(marker.width_mm));
  const [height, setHeight] = useState(marker === null ? '' : String(marker.height_mm));
  const [dictionary, setDictionary] = useState<ArucoDictionary | typeof NO_FIDUCIAL>(
    marker?.aruco_dictionary ?? NO_FIDUCIAL,
  );
  const [arucoId, setArucoId] = useState(
    marker?.aruco_id === null || marker?.aruco_id === undefined ? '' : String(marker.aruco_id),
  );
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const nameId = useId();
  const widthId = useId();
  const heightId = useId();
  const dictionaryId = useId();
  const arucoIdId = useId();
  const dimensionHintId = useId();

  /**
   * The id range the chosen family actually holds.
   *
   * Rendered rather than only enforced: `DICT_4X4_50` holds ids 0–49, and an
   * Administrator printing a card has to pick a number *before* they get here.
   * Telling them the range after they typed 60 is a worse form than telling
   * them before.
   */
  const idLimit = dictionary === NO_FIDUCIAL ? null : ARUCO_DICTIONARY_SIZES[dictionary] - 1;

  async function save(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setFailure(null);

    // `null` clears the pair server-side; the both-or-neither rule is enforced
    // there and in the database, so this only has to send a coherent pair.
    const body = {
      name,
      width_mm: Number(width),
      height_mm: Number(height),
      aruco_dictionary: dictionary === NO_FIDUCIAL ? null : dictionary,
      aruco_id: dictionary === NO_FIDUCIAL ? null : Number(arucoId),
    };

    try {
      asMarker(
        await apiRequest(editing ? `/admin/markers/${marker.id}` : '/admin/markers', {
          method: editing ? 'PATCH' : 'POST',
          body,
        }),
      );
      onSaved();
    } catch (error) {
      // The API's own sentence wherever there is one (EXPERIENCE.md:87) —
      // this screen never composes its own version of a rule it does not own.
      setFailure(error instanceof ApiRequestError ? error.message : COULD_NOT_SAVE);
      setBusy(false);
    }
  }

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>{editing ? `Edit ${marker.name}` : 'Register a marker'}</h1>

      {failure !== null && (
        <p className={styles.failure} role="alert">
          {failure}
        </p>
      )}

      <form className={styles.form} onSubmit={(event) => void save(event)}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={nameId}>
            Name
          </label>
          <input
            className={styles.input}
            id={nameId}
            type="text"
            value={name}
            maxLength={MAX_MARKER_NAME_LENGTH}
            required
            onChange={(event) => setName(event.target.value)}
          />
          <p className={styles.hint}>
            What staff will see in the picker — “Rocell ID badge”, “Bank card”.
          </p>
        </div>

        <div className={styles.pair}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={widthId}>
              Width (mm)
            </label>
            <input
              className={styles.input}
              id={widthId}
              type="number"
              inputMode="decimal"
              step="0.01"
              min={MIN_MARKER_EDGE_MM}
              max={MAX_MARKER_EDGE_MM}
              value={width}
              required
              aria-describedby={dimensionHintId}
              onChange={(event) => setWidth(event.target.value)}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={heightId}>
              Height (mm)
            </label>
            <input
              className={styles.input}
              id={heightId}
              type="number"
              inputMode="decimal"
              step="0.01"
              min={MIN_MARKER_EDGE_MM}
              max={MAX_MARKER_EDGE_MM}
              value={height}
              required
              aria-describedby={dimensionHintId}
              onChange={(event) => setHeight(event.target.value)}
            />
          </div>
        </div>
        {/* The one hint that carries real risk. Both fields point at it. */}
        <p className={styles.hint} id={dimensionHintId}>
          Measure the printed black square itself, not the paper around it, in millimetres. A bank
          card is 85.6 × 54. Everything measured with this marker is scaled by these two numbers.
        </p>

        <fieldset className={styles.fiducialGroup}>
          <legend className={styles.legend}>Printed fiducial</legend>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={dictionaryId}>
              Dictionary
            </label>
            <select
              className={styles.select}
              id={dictionaryId}
              value={dictionary}
              onChange={(event) =>
                setDictionary(
                  event.target.value === NO_FIDUCIAL
                    ? NO_FIDUCIAL
                    : (event.target.value as ArucoDictionary),
                )
              }
            >
              <option value={NO_FIDUCIAL}>None — corners are tapped by hand</option>
              {ARUCO_DICTIONARIES.map((entry) => (
                <option key={entry} value={entry}>
                  {entry}
                </option>
              ))}
            </select>
            <p className={styles.hint}>
              A printed ArUco marker is found in the photo automatically. Without one, staff tap the
              marker’s four corners themselves — which works with any object of known size.
            </p>
          </div>

          {dictionary !== NO_FIDUCIAL && (
            <div className={styles.field}>
              <label className={styles.label} htmlFor={arucoIdId}>
                Marker id
              </label>
              <input
                className={styles.input}
                id={arucoIdId}
                type="number"
                inputMode="numeric"
                step="1"
                min={0}
                max={idLimit ?? undefined}
                value={arucoId}
                required
                onChange={(event) => setArucoId(event.target.value)}
              />
              <p className={styles.hint}>
                The number printed on the card. {dictionary} holds ids 0 to {idLimit}.
              </p>
            </div>
          )}
        </fieldset>

        <div className={styles.actions}>
          <button className={styles.submit} type="submit" disabled={busy}>
            {editing ? 'Save changes' : 'Register marker'}
          </button>
          <button className={styles.back} type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
