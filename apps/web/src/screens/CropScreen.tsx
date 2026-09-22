import { useEffect, useRef } from 'react';
import type { JSX } from 'react';

import styles from './CropScreen.module.css';

/**
 * Crop — a placeholder for Story 3.2's real crop editor (Story 3.1).
 *
 * Deliberately inert: it shows the image `ScanScreen` handed off and a Back
 * control, and nothing else. No free-form crop selector, no drag handles, no
 * normalized crop rectangle, no blur/framing check, no "Confirm Crop" and no
 * backend endpoint — all of those are later Epic 3 stories, and building even
 * a placeholder version of "Confirm Crop" now would both violate DESIGN.md's
 * one-accent-per-screen rule ahead of schedule and hand Story 3.2 a control to
 * rip out rather than one to build. That is also why this screen carries no
 * accent button at all: Back is the only control, and it is the secondary,
 * navy-outline treatment.
 *
 * Rendered *inside* the shell, in place of the home panel, exactly as
 * `ScanScreen` is — no `<main>` of its own; `AppShell` already provides the
 * one the gate's focus effect moves focus to on a screen swap.
 */

interface CropScreenProps {
  /** The downscaled Blob `ScanScreen` produced, from either path. */
  image: Blob;
  /** Discards `image` and returns to Scan. */
  onBack: () => void;
}

export function CropScreen({ image, onBack }: CropScreenProps): JSX.Element {
  const imgRef = useRef<HTMLImageElement>(null);

  // Created and revoked inside the same effect, keyed on `image` — never
  // split into a `useMemo` for the create half. React does not guarantee a
  // `useMemo` computation survives being discarded and re-run (Strict Mode's
  // dev double-invoke does exactly that), which risks a URL created once and
  // never revoked. Keeping create-and-revoke as one pair in one effect means
  // there is never a URL this component created that isn't matched by
  // exactly one `revokeObjectURL` call.
  //
  // Assigned straight onto the `<img>` element rather than through state:
  // `oxlint`'s `react/set-state-in-effect` forbids calling a setter inside an
  // effect, and there is nothing here a second render would improve — the
  // element already exists (it carries no other data-dependent prop), so this
  // is the same "bind directly, once the node exists" move `ScanScreen` makes
  // for the live stream's `srcObject`.
  useEffect(() => {
    const url = URL.createObjectURL(image);
    if (imgRef.current !== null) {
      imgRef.current.src = url;
    }
    // Revoked on unmount and whenever `image` changes and a new URL replaces
    // this one, so a Blob URL never outlives the element that pointed at it —
    // the same reason a browser tab that never revoked one would leak memory
    // for the life of the session.
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [image]);

  return (
    <section className={styles.screen}>
      <h1 className={styles.title}>Crop</h1>

      <div className={styles.preview}>
        <img className={styles.image} ref={imgRef} alt="Captured tile, not yet cropped" />
      </div>

      <div className={styles.actions}>
        <button className={styles.back} type="button" onClick={onBack}>
          Back
        </button>
      </div>
    </section>
  );
}
