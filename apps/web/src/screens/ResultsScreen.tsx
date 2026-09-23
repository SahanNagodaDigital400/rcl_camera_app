import { ArrowsClockwise, CaretDown, CaretUp, Crop } from '@phosphor-icons/react';
import { useState } from 'react';
import type { JSX } from 'react';

import { API_PREFIX } from '../api/client';
import { ImageViewer } from '../components/ImageViewer';
import styles from './ResultsScreen.module.css';
import { UNKNOWN_CATEGORY } from '@rocell/schema/tile';
import type { ScanCandidate } from '@rocell/schema/scan';

/**
 * Results — up to three ranked Candidates from a submitted Scan (Story 3.4).
 *
 * Reached from a capture on Scan (the whole frame, submitted directly) or
 * from a confirmed crop (`App`'s `showResults`, candidates first, then the
 * section). Renders the closed `ScanCandidate` array `POST /scans` answered —
 * `tile_id`, `code`, `size`, `category`, `image_id`, never a `score` or a
 * `rank` (AD-20). **Order in the array is the rank**: the first element is
 * painted as "Best match" and the ordinal is never re-derived or displayed
 * anywhere else.
 *
 * **The best match is shown, the rest are one tap away.** The server still
 * answers with three Candidates and this screen still holds all three — a
 * single answer is confidently wrong often enough that the alternatives can
 * never be dropped (PRD product rule). They are collapsed, not discarded:
 * the disclosure under the card says how many there are and reveals them in
 * place, so the common case (the first card is right) is one glance and the
 * uncommon one is one tap. No threshold decides this and nothing is hidden
 * on the strength of a score.
 *
 * **Each card is a distinct Tile, never deduplicated, collapsed or
 * diversified by Category** (AD-18) — two Candidates from one Category folder
 * each keep their own slot, exactly as the server sent them.
 *
 * **Every image is proxied, never a storage URL** (AD-9). A card's `src` is
 * `GET /tiles/{tileId}/images/{imageId}` on this same origin, so the session
 * cookie travels with it and the server re-checks the caller's claimed-user
 * status on every request.
 *
 * **Tapping a card opens its reference image full-screen** — the
 * verification moment EXPERIENCE.md names: a member of staff cannot verify a
 * code they do not recognise, but they can verify a picture instantly. Each
 * card is a real `<button>` for that reason, at the touch-target floor, and
 * the line under the heading says so (`mockups/key-results.html`).
 *
 * **Two ways forward, both secondary.** "Scan again" returns to the live
 * viewfinder; "Adjust crop" opens the optional crop editor on the very frame
 * these candidates came from, for the case where the tile was small in it.
 * Neither takes the accent: the cards are what this screen is for.
 *
 * **An empty array is not an empty screen.** "No confident match" is the
 * PRD's own answer for a catalogue with nothing indexed yet, and it is
 * rendered as EXPERIENCE.md's verbatim sentence plus a single Retake action
 * — with the crop offered beside it, since a tighter frame is the other
 * thing that can rescue a photo.
 */

const NO_MATCH = 'No confident match — retake, or ask a colleague.';
const BEST_MATCH = 'Best match';
const RETAKE = 'Retake';
const SCAN_AGAIN = 'Scan again';
const ADJUST_CROP = 'Adjust crop';
const HOW_TO_VERIFY = 'Tap a candidate to view its reference image full-screen.';
const HIDE_OTHERS = 'Hide other matches';

/** "Show 2 other matches" — the count is the point: it says what is behind it. */
function showOthersLabel(count: number): string {
  return `Show ${count} other match${count === 1 ? '' : 'es'}`;
}

function imageSrc(candidate: ScanCandidate): string {
  return `${API_PREFIX}/tiles/${candidate.tile_id}/images/${candidate.image_id}`;
}

function imageAlt(candidate: ScanCandidate): string {
  return `Reference image of ${candidate.code}`;
}

interface ResultsScreenProps {
  candidates: ScanCandidate[];
  /** Back to the live viewfinder for another photo. */
  onBack: () => void;
  /**
   * Open the crop editor on the frame these candidates came from. Omitted
   * when no frame is held (there is always one today), and then no control
   * is rendered.
   */
  onAdjustCrop?: (() => void) | undefined;
}

export function ResultsScreen({
  candidates,
  onBack,
  onAdjustCrop,
}: ResultsScreenProps): JSX.Element {
  /** The Candidate whose reference image is open full-screen, or `null`. */
  const [viewing, setViewing] = useState<ScanCandidate | null>(null);
  /** Whether the Candidates below the best match are revealed. */
  const [showOthers, setShowOthers] = useState(false);

  const adjust =
    onAdjustCrop === undefined ? null : (
      <button className={styles.adjust} type="button" onClick={onAdjustCrop}>
        <Crop className={styles.buttonIcon} aria-hidden="true" />
        {ADJUST_CROP}
      </button>
    );

  /* All three are held and none is thrown away — only the alternatives are
     folded up until asked for. */
  const others = candidates.length - 1;
  const shown = showOthers ? candidates : candidates.slice(0, 1);

  if (candidates.length === 0) {
    return (
      <section className={styles.screen}>
        <h1 className={styles.title}>Results</h1>
        <p className={styles.empty}>{NO_MATCH}</p>
        <div className={styles.actions}>
          {/* Retake is the one accent action: the camera is the answer to a
              photo nothing matched. The crop is the quieter alternative. */}
          <button className={styles.confirm} type="button" onClick={onBack}>
            {RETAKE}
          </button>
          {adjust}
        </div>
      </section>
    );
  }

  return (
    <section className={styles.screen}>
      <div className={styles.header}>
        <h1 className={styles.title}>Results</h1>
        <p className={styles.subheading}>{HOW_TO_VERIFY}</p>
      </div>
      <div className={styles.list}>
        {shown.map((candidate, index) => (
          <button
            className={index === 0 ? `${styles.card} ${styles.cardBest}` : styles.card}
            key={candidate.tile_id}
            type="button"
            onClick={() => setViewing(candidate)}
          >
            <img alt={imageAlt(candidate)} className={styles.refImage} src={imageSrc(candidate)} />
            <span className={styles.info}>
              {/* Never a percentage, a bar or a derived word — the border and
                  this one pill are the whole of the rank signal (AD-20). */}
              {index === 0 && <span className={styles.bestPill}>{BEST_MATCH}</span>}
              <span className={styles.code}>{candidate.code}</span>
              <span className={styles.meta}>
                {candidate.size} · {candidate.category ?? UNKNOWN_CATEGORY}
              </span>
            </span>
          </button>
        ))}
        {others > 0 && (
          /* A disclosure, not a navigation: the other Candidates open in
             place, under the card they are alternatives to. */
          <button
            className={styles.more}
            type="button"
            aria-expanded={showOthers}
            onClick={() => setShowOthers(!showOthers)}
          >
            {showOthers ? (
              <CaretUp className={styles.buttonIcon} aria-hidden="true" />
            ) : (
              <CaretDown className={styles.buttonIcon} aria-hidden="true" />
            )}
            {showOthers ? HIDE_OTHERS : showOthersLabel(others)}
          </button>
        )}
      </div>
      <div className={styles.actions}>
        <button className={styles.rescan} type="button" onClick={onBack}>
          <ArrowsClockwise className={styles.buttonIcon} aria-hidden="true" />
          {SCAN_AGAIN}
        </button>
        {adjust}
      </div>
      {viewing !== null && (
        <ImageViewer
          alt={imageAlt(viewing)}
          src={imageSrc(viewing)}
          onClose={() => setViewing(null)}
        />
      )}
    </section>
  );
}
