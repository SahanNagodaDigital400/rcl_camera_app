import { Camera, Image as ImageIcon } from '@phosphor-icons/react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, JSX, PointerEvent } from 'react';

import { matchSize } from '@rocell/schema/marker';
import type { Marker, Measurement, Point } from '@rocell/schema/marker';

import {
  ApiRequestError,
  fetchScanMarkers,
  fetchScanSizes,
  MARKER_NOT_DETECTED,
  measureTile,
  proposeTile,
} from '../api/client';
import { toMeasuringFrame } from '../scan/downscaleImage';
import { useRearCamera } from '../scan/useRearCamera';
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

/**
 * **The centre, and that is a measured choice rather than the obvious one.**
 *
 * An earlier version of this sentence said "near a corner", on the strength of
 * an experiment that composited the marker onto reference images — where the
 * tile fills the whole frame, so a tile corner is a frame corner and falls
 * outside the 224px centre crop the embedding sees. Real photographs are not
 * like that: the tile sits inside a wider frame, the embedded window is the
 * middle ~88% x 66% of it, and a marker at the tile's corner lands squarely
 * inside. Placement changed nothing.
 *
 * Re-measured against the real framing, the marker costs about **2 points** of
 * top-1 wherever it is put (24.0% bare against 22.0% with it) — and since this
 * screen takes its own photograph, it costs nothing at all. The centre is then
 * simply the better place: the detector has the most margin there, and the
 * tile's four corners stay clear of it for dragging.
 */
const TAKE_A_PHOTO =
  'Place the marker flat in the centre of the tile and take a photo of both.';
const DRAG_THE_CORNERS =
  'Drag each corner onto the tile’s corner. Tap anywhere to move the nearest one.';
const TAP_THE_MARKER =
  'The marker was not found automatically. Tap the marker’s four corners too, in any order.';
const PROPOSING = 'Looking for the tile…';
const NO_MARKERS =
  'No markers are registered, so there is nothing to measure against. An administrator ' +
  'registers one on the Markers screen.';
const COULD_NOT_MEASURE = 'The measurement could not be taken.';
const CAMERA_EXPLANATION =
  'Measuring needs your camera. Nothing is captured until you tap the shutter.';
const CAMERA_DENIED = 'Camera access was not granted. You can still choose a photo below.';
const CAMERA_CHECKING = 'Checking the camera…';
const CAMERA_STARTING = 'Starting the camera…';
const DECODE_FAILURE = 'That file is not a readable image. Choose another.';
const PROCESS_FAILURE = 'Could not process that image. Try again.';

/**
 * The tapped corners in perimeter order — **the server's own ordering**.
 *
 * `api.measure.order_corners` sorts by angle about the centroid and starts
 * at the corner nearest the top-left, so drawing them in tap order would
 * show a shape the measurement does not use. Mirroring the rule here is what
 * makes the outline a genuine preview: if the drawn quad is not the tile,
 * the measurement will not be either, and that is visible before pressing
 * Measure rather than afterwards as a number that looks plausible.
 */
function inPerimeterOrder(points: readonly Point[]): readonly Point[] {
  if (points.length < 3) return points;
  const cx = points.reduce((t, p) => t + p.x, 0) / points.length;
  const cy = points.reduce((t, p) => t + p.y, 0) / points.length;
  // `Array#toSorted` is the rule's own suggestion and is an ES2023 method the
  // project's `lib` does not declare (`tsconfig.json` targets ES2022), so it
  // does not typecheck here — `AuditLogScreen.detailsText` carries the same
  // note. The mutation the rule guards against cannot happen either way: the
  // spread makes a fresh array nothing else holds a reference to.
  // oxlint-disable-next-line unicorn/no-array-sort
  const clockwise = [...points].sort(
    (a, b) => Math.atan2(a.y - cy, a.x - cx) - Math.atan2(b.y - cy, b.x - cx),
  );
  let start = 0;
  clockwise.forEach((p, i) => {
    const best = clockwise[start];
    if (best !== undefined && p.x + p.y < best.x + best.y) start = i;
  });
  return [...clockwise.slice(start), ...clockwise.slice(0, start)];
}

/**
 * The quadrilateral a photo opens on when the server cannot propose one.
 *
 * A generous box rather than the frame's corners: it has to be obviously *not*
 * the tile, so nobody measures it by accident, while still being close enough
 * that each corner is a short drag from where it belongs.
 */
const DEFAULT_QUAD: readonly Point[] = [
  { x: 0.25, y: 0.25 },
  { x: 0.75, y: 0.25 },
  { x: 0.75, y: 0.75 },
  { x: 0.25, y: 0.75 },
];

/**
 * Where a pointer event landed, normalized against **the photograph itself**.
 *
 * Measured off the `<img>` rather than the element the event fired on, and
 * that is the whole of it: the server maps these fractions onto the image's
 * own pixels, so anything measured against a box that is not exactly the
 * picture puts every corner somewhere it was not placed. A letterboxed photo
 * did precisely that — no error at the centre, growing toward the edges,
 * which is where a tile's corners are.
 */
function at(image: HTMLImageElement | null, clientX: number, clientY: number): Point | null {
  if (image === null) return null;
  const bounds = image.getBoundingClientRect();
  if (bounds.width === 0 || bounds.height === 0) return null;
  return {
    x: Math.min(Math.max((clientX - bounds.left) / bounds.width, 0), 1),
    y: Math.min(Math.max((clientY - bounds.top) / bounds.height, 0), 1),
  };
}

/** The index of the corner nearest `point`, of whichever quad is in hand. */
function nearestTo(point: Point, corners: readonly Point[]): number {
  let best = 0;
  let bestGap = Number.POSITIVE_INFINITY;
  corners.forEach((corner, index) => {
    const gap = (corner.x - point.x) ** 2 + (corner.y - point.y) ** 2;
    if (gap < bestGap) {
      bestGap = gap;
      best = index;
    }
  });
  return best;
}

/** The longer of two lengths, never zero, so a ratio against it is safe. */
function longerOf(a: number, b: number): number {
  return Math.max(a, b) === 0 ? 1 : Math.max(a, b);
}

/**
 * Apply a row-major 3x3 homography to a normalized point.
 *
 * The preview half of the measurement: the server solved this matrix from the
 * marker it found, so applying it here gives the same millimetres without a
 * round trip — which is what lets the readout follow a corner while it is
 * being dragged. `POST /scans/measure` recomputes from scratch and is the only
 * number anybody acts on.
 */
function toMillimetres(h: readonly number[], point: Point): Point | null {
  const w = (h[6] ?? 0) * point.x + (h[7] ?? 0) * point.y + (h[8] ?? 0);
  if (w === 0 || !Number.isFinite(w)) return null;
  return {
    x: ((h[0] ?? 0) * point.x + (h[1] ?? 0) * point.y + (h[2] ?? 0)) / w,
    y: ((h[3] ?? 0) * point.x + (h[4] ?? 0) * point.y + (h[5] ?? 0)) / w,
  };
}

/**
 * The quad's two edge lengths in millimetres, short edge first, or `null`.
 *
 * Opposite edges are averaged, exactly as `api.measure.measure_tile` averages
 * them: both are measurements of the same physical edge, and the average
 * halves the error of a single misplaced corner.
 */
function previewSize(
  homography: readonly number[] | null,
  corners: readonly Point[],
): { short: number; long: number; rectangular: boolean } | null {
  if (homography === null || homography.length !== 9 || corners.length !== QUAD_CORNERS) {
    return null;
  }
  const flat = inPerimeterOrder(corners).map((c) => toMillimetres(homography, c));
  if (flat.some((p) => p === null)) return null;
  const points = flat as Point[];
  const edge = (a: number, b: number): number => {
    const from = points[a];
    const to = points[b];
    if (from === undefined || to === undefined) return 0;
    return Math.hypot(to.x - from.x, to.y - from.y);
  };
  const horizontal = (edge(0, 1) + edge(2, 3)) / 2;
  const vertical = (edge(1, 2) + edge(3, 0)) / 2;
  if (!Number.isFinite(horizontal) || !Number.isFinite(vertical)) return null;

  /**
   * Whether this still measures as a rectangle once perspective is undone.
   *
   * A tile *is* one, so in the marker's plane its opposite edges and its two
   * diagonals must come back equal. They will not be exactly equal — a dragged
   * corner, a marker a millimetre out of plane — so it is a tolerance, and it
   * mirrors `api.measure.RECTANGULARITY_TOLERANCE`.
   *
   * **A warning, not a refusal.** The server used to reject on this, which
   * stopped a measurement the staff member could see was right. They have the
   * outline and the millimetres in front of them; what this adds is a nudge
   * that the marker may not be flat, which no number would show.
   */
  const diagonal = (a: number, b: number): number => {
    const from = points[a];
    const to = points[b];
    if (from === undefined || to === undefined) return 0;
    return Math.hypot(to.x - from.x, to.y - from.y);
  };
  const pairs: [number, number][] = [
    [edge(0, 1), edge(2, 3)],
    [edge(1, 2), edge(3, 0)],
    [diagonal(0, 2), diagonal(1, 3)],
  ];
  const rectangular = pairs.every(([a, b]) => Math.abs(a - b) / longerOf(a, b) <= 0.2);

  return {
    short: Math.min(horizontal, vertical),
    long: Math.max(horizontal, vertical),
    rectangular,
  };
}

/**
 * A quad as an SVG `points` string, in percent.
 *
 * Fixed to two decimals because `0.45 * 100` is `45.00000000000001` in
 * floating point, and an attribute full of that is unreadable in a DOM
 * inspector and unmatchable in a test. Two decimals is a hundredth of a
 * percent of the photo's width — far below a pixel.
 */
function asPoints(corners: readonly Point[]): string {
  return corners.map((c) => `${(c.x * 100).toFixed(2)},${(c.y * 100).toFixed(2)}`).join(' ');
}

interface MeasureScreenProps {
  /**
   * Accept the measured Size. `ScanScreen` pre-fills its picker with it; the
   * staff member confirms or changes it before the scan is submitted.
   */
  onUseSize: (size: string) => void;
  /** Back to Scan without measuring. */
  onBack: () => void;
}

export function MeasureScreen({ onUseSize, onBack }: MeasureScreenProps): JSX.Element {
  /**
   * The photograph being measured — **this screen's own, never the scan's.**
   *
   * The two cannot be one picture, and that is measured rather than assumed:
   * matching an A4 marker sheet lying centred on the tile costs 24 points of
   * top-1 accuracy (75.6% against 100% on 45 catalogue tiles), because
   * `shared/vision` resizes the shortest edge to 256 and centre-crops 224 —
   * so the sheet fills much of the only region the embedding ever sees.
   * Laying the marker at the tile's edge recovers half of that and no more,
   * and cropping clear of it recovers 4 points, because a narrow crop then
   * mismatches the reference on scale instead.
   *
   * So matching wants the surface clean and measuring wants a marker on it,
   * and one shutter press cannot serve both. Scan first with nothing on the
   * tile; place the marker only for this.
   *
   * **Taken the way the scan is taken, through `useRearCamera` and the same
   * canvas encode.** This screen used to open the phone's camera app with
   * `capture="environment"` and measure the file it handed back. That file
   * carries its EXIF orientation, and a browser honours that tag while a
   * server may not — so a photograph taken with the phone turned arrived
   * upright on screen and on its side at `POST /scans/propose`, and the marker
   * outline drawn over it was a transposed square. A canvas re-encode has no
   * EXIF at all: the rotation is in the pixels, and there is no tag left for
   * the two halves to disagree about.
   */
  const [photo, setPhoto] = useState<Blob | null>(null);
  const [markers, setMarkers] = useState<readonly Marker[] | null>(null);
  /**
   * The Sizes the index can actually answer for.
   *
   * Read here because the match is made here: the homography and the corners
   * are both already in hand, so there is nothing a second upload would add
   * except a round trip on a showroom connection. `[]` while it loads and on
   * a failure, which shows the millimetres with no Size suggested — the
   * truthful answer when nothing is known to match against.
   */
  const [sizes, setSizes] = useState<readonly string[]>([]);
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
  /** The corner currently under the finger, or `null`. */
  const [dragging, setDragging] = useState<number | null>(null);
  /** Whether the server is being asked where the tile is. */
  const [proposing, setProposing] = useState(false);
  /** Where the fiducial was found, so it can be drawn and checked. */
  const [markerOutline, setMarkerOutline] = useState<readonly Point[]>([]);
  /** The proposal's normalized-to-millimetres matrix, for the live readout. */
  const [homography, setHomography] = useState<readonly number[] | null>(null);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** Whether a frame is being read off the camera and encoded. */
  const [capturing, setCapturing] = useState(false);

  // The camera itself — `ScanScreen`'s hook, not a second one. Measuring and
  // matching photograph the same tile, so they open the same stream under the
  // same constraints and encode through the same canvas.
  const { cameraState, attachVideo, enableCamera, videoElement } = useRearCamera();

  const markerFieldId = useId();
  const photoFieldId = useId();
  const fileInputRef = useRef<HTMLInputElement>(null);
  /** The picture itself — the one box corner coordinates may be measured against. */
  const photoRef = useRef<HTMLImageElement>(null);
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
  const photoUrl = useMemo(() => (photo === null ? null : URL.createObjectURL(photo)), [photo]);
  useEffect(
    () => () => {
      if (photoUrl !== null) URL.revokeObjectURL(photoUrl);
    },
    [photoUrl],
  );

  useEffect(() => {
    void fetchScanSizes()
      .then((available) => {
        if (mountedRef.current) setSizes(available);
      })
      .catch(() => {
        // See `sizes`: no list means no suggestion, never a rejection.
      });
  }, []);

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
   * Hold a new frame, and forget everything the last one meant.
   *
   * Corners tapped on the previous photo describe nothing on this one, and a
   * measurement carried over would be a number on screen that no longer
   * describes what is under it. The marker outline and the homography go too:
   * both belong to the proposal for a photograph that is no longer here, and
   * leaving them would draw the old marker over the new tile until the next
   * proposal lands. The fallback decision is reset as well — a fresh frame
   * deserves a fresh attempt at automatic detection.
   */
  function accept(frame: Blob): void {
    if (!mountedRef.current) return;
    setPhoto(frame);
    setTileCorners([]);
    setMarkerCorners([]);
    setMarkerOutline([]);
    setHomography(null);
    setTapMarker(false);
    setMeasurement(null);
    setFailure(null);
  }

  /** Back to the viewfinder, holding nothing. */
  function retake(): void {
    setPhoto(null);
    setTileCorners([]);
    setMarkerCorners([]);
    setMarkerOutline([]);
    setHomography(null);
    setTapMarker(false);
    setMeasurement(null);
    setFailure(null);
  }

  /**
   * Read the live frame, whole, at `MEASURE_MAX_EDGE`.
   *
   * **Whole, where the scan takes the centre square.** That is the one place
   * the two shutters differ, and it is the reason measuring has a shutter of
   * its own: `api.measure` locates the marker's corners in the pixels it is
   * handed and refuses a marker under 60 of them, and a centre square can crop
   * the marker out of the frame altogether.
   */
  async function capture(): Promise<void> {
    const video = videoElement();
    if (video === null) return;
    // A tap that lands before the stream's first frame has decoded would
    // otherwise draw and encode a 0x0 canvas.
    if (video.videoWidth === 0 || video.videoHeight === 0) return;

    setFailure(null);
    setCapturing(true);
    try {
      accept(await toMeasuringFrame(video, video.videoWidth, video.videoHeight));
    } catch {
      if (mountedRef.current) setFailure(PROCESS_FAILURE);
    } finally {
      if (mountedRef.current) setCapturing(false);
    }
  }

  /**
   * Measure a photograph taken somewhere else.
   *
   * `imageOrientation: 'from-image'` is doing real work: it reads the file's
   * own EXIF orientation during the decode, so the bitmap is upright before
   * anything is drawn from it and the re-encoded frame carries no tag for the
   * server to interpret differently. This is the same decode `ScanScreen`'s
   * upload path runs, for the same reason.
   */
  async function choosePhoto(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    // Cleared before anything else: a browser does not fire `change` again
    // for the same file re-chosen, so a retry of the very photo that just
    // failed would be unreachable without this.
    if (fileInputRef.current !== null) fileInputRef.current.value = '';
    if (file === undefined) return;

    setFailure(null);
    let bitmap: ImageBitmap;
    try {
      bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch {
      if (mountedRef.current) setFailure(DECODE_FAILURE);
      return;
    }
    try {
      accept(await toMeasuringFrame(bitmap, bitmap.width, bitmap.height));
    } catch {
      if (mountedRef.current) setFailure(PROCESS_FAILURE);
    } finally {
      bitmap.close();
    }
  }

  /**
   * Ask the server where the tile is, and open on its answer.
   *
   * **A starting shape, and the copy never says more than that.** On real
   * showroom photographs the detector is wrong more often than right — tiles
   * are laid against neighbours of near-identical tone, so a tile's boundary
   * is no more contrasty than its own veining — and `detected` coming back
   * `true` has been observed on quads that were not the tile. So the
   * instruction is always "drag each corner onto the tile's corner", never
   * "we found it", and every corner is moved by a person before anything is
   * measured.
   *
   * A refusal is not surfaced: the fallback is the default quad, which is what
   * the staff member would be dragging anyway.
   */
  useEffect(() => {
    if (photo === null || markerId === '') return;
    let current = true;
    void Promise.resolve()
      .then(() => {
        if (current && mountedRef.current) setProposing(true);
      })
      .then(async () => proposeTile(photo, markerId))
      .then((proposal) => {
        if (!current || !mountedRef.current) return;
        setTileCorners(proposal.corners);
        setMarkerOutline(proposal.marker);
        setHomography(proposal.homography);
      })
      .catch(() => {
        if (!current || !mountedRef.current) return;
        setTileCorners(DEFAULT_QUAD);
        setMarkerOutline([]);
        setHomography(null);
      })
      .finally(() => {
        if (current && mountedRef.current) setProposing(false);
      });
    return () => {
      current = false;
    };
  }, [photo, markerId]);

  /**
   * The size the corners currently describe, updated as they move.
   *
   * Recomputed on every render rather than stored: it is derived from the
   * corners and the matrix, and a copy in state is a second thing that can be
   * stale while a finger is mid-drag.
   */
  const preview = previewSize(homography, tileCorners);

  /**
   * The Size the corners currently support, or `null`.
   *
   * **Matched here, not on the server.** The homography arrived with the
   * proposal and the corners are on this screen, so the millimetres are
   * already known — uploading the photograph a second time to have the same
   * arithmetic done again is a round trip that adds nothing. `matchSize` is
   * the twin of `shared_schema.marker.match_size`, rule for rule, so the
   * answer is the one the server would have given.
   *
   * The fallback path — a marker the detector could not find, whose corners
   * were tapped — has no homography, and there `measurement` holds what
   * `POST /scans/measure` worked out instead.
   */
  const matchedSize =
    preview !== null ? matchSize(preview.short, preview.long, sizes) : measurement?.matched_size ?? null;

  /** Which quad the next tap belongs to. */
  const collecting = tapMarker ? markerCorners : tileCorners;
  const complete = tapMarker
    ? markerCorners.length === QUAD_CORNERS && tileCorners.length === QUAD_CORNERS
    : tileCorners.length === QUAD_CORNERS;

  function instruction(): string {
    if (markers !== null && markers.length === 0) return NO_MARKERS;
    if (photo === null) return TAKE_A_PHOTO;
    if (proposing) return PROPOSING;
    if (tapMarker && markerCorners.length < QUAD_CORNERS) return TAP_THE_MARKER;
    return DRAG_THE_CORNERS;
  }

  function moveCorner(index: number, point: Point): void {
    const next = collecting.map((corner, i) => (i === index ? point : corner));
    if (tapMarker) setMarkerCorners(next);
    else setTileCorners(next);
    setMeasurement(null);
  }

  /**
   * Grab the nearest corner and start moving it.
   *
   * **Tap and drag are one gesture, not two.** A tap moves the nearest corner
   * to where the finger landed and a drag keeps moving it — which is what
   * makes a corner correctable rather than re-collectable. It also means a
   * corner behind a fingertip can be placed by tapping just beside it and
   * sliding, instead of being invisible under the thumb that is placing it.
   *
   * While the marker's corners are being collected by hand the quad may be
   * shorter than four; a tap then appends rather than moves, because there is
   * nothing yet to move.
   */
  function grab(event: PointerEvent<HTMLDivElement>): void {
    const point = at(photoRef.current, event.clientX, event.clientY);
    if (point === null) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    if (collecting.length < QUAD_CORNERS) {
      const next = [...collecting, point];
      if (tapMarker) setMarkerCorners(next);
      else setTileCorners(next);
      setMeasurement(null);
      return;
    }
    const index = nearestTo(point, collecting);
    setDragging(index);
    moveCorner(index, point);
  }

  function drag(event: PointerEvent<HTMLDivElement>): void {
    if (dragging === null) return;
    const point = at(photoRef.current, event.clientX, event.clientY);
    if (point !== null) moveCorner(dragging, point);
  }

  async function measure(): Promise<void> {
    setBusy(true);
    setFailure(null);
    try {
      if (photo === null) return;
      const answer = await measureTile(
        photo,
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
      {markerOutline.length === QUAD_CORNERS && (
        // Everything is scaled by the marker: a detector that locked onto
        // something else produces millimetres wrong by that ratio, and nothing
        // else on this screen would show it.
        <p className={styles.markerNote}>
          The blue outline is the marker the measurement is scaled by. Retake if it is not on the
          printed square.
        </p>
      )}
      {preview !== null && (
        <p className={styles.preview}>
          {`Currently ${String(Math.round(preview.short))} × ${String(Math.round(preview.long))} mm`}
        </p>
      )}
      {tapMarker && markerCorners.length < QUAD_CORNERS && (
        <p className={styles.progress}>
          {`${String(markerCorners.length)} of ${String(QUAD_CORNERS)} marker corners tapped.`}
        </p>
      )}

      {photoUrl === null ? (
        /* The same viewfinder the scan is taken through, and deliberately not
           `capture="environment"`. The camera app returns its own file with
           the EXIF orientation left in, and a measurement is geometry over
           those pixels: the browser rotates by that tag and the server need
           not, which is how an upright photograph came to be measured on its
           side. The shutter here encodes through a canvas, so the frame that
           reaches `POST /scans/propose` is oriented exactly as the frame on
           screen. */
        <div className={styles.viewfinder} aria-busy={capturing}>
          {cameraState === 'granted' ? (
            <video
              autoPlay
              className={styles.video}
              data-testid="measure-viewfinder-video"
              muted
              playsInline
              ref={attachVideo}
            />
          ) : cameraState === 'denied' ? (
            <p className={styles.denied}>{CAMERA_DENIED}</p>
          ) : cameraState === 'checking' || cameraState === 'starting' ? (
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

          {/* Three columns, not `space-between`: the shutter stays optically
              centred and the fallback can never collide with it, whatever the
              label's rendered width. */}
          <div className={styles.controls}>
            <div className={styles.uploadField}>
              <label className={styles.uploadLabel} htmlFor={photoFieldId}>
                <ImageIcon className={styles.uploadIcon} aria-hidden="true" />
                Choose a photo
              </label>
              <input
                accept="image/*"
                className={styles.fileInput}
                disabled={capturing || markerId === ''}
                id={photoFieldId}
                ref={fileInputRef}
                type="file"
                onChange={(event) => void choosePhoto(event)}
              />
            </div>

            {cameraState === 'granted' && (
              <button
                className={`${styles.primary} ${styles.shutter}`}
                type="button"
                onClick={() => void capture()}
                disabled={capturing || markerId === ''}
              >
                <Camera className={styles.shutterIcon} aria-hidden="true" />
                <span className={styles.shutterLabel}>Capture</span>
              </button>
            )}

            <div className={styles.controlsSpacer} aria-hidden="true" />
          </div>
        </div>
      ) : (
        <div
          aria-label="The tile being measured"
          className={styles.canvas}
          role="application"
          onPointerDown={grab}
          onPointerMove={drag}
          onPointerUp={() => setDragging(null)}
          onPointerCancel={() => setDragging(null)}
        >
          <img alt="" className={styles.photo} ref={photoRef} src={photoUrl} />
          {tileCorners.length > 2 && (
            <svg
              aria-hidden="true"
              className={styles.outline}
              preserveAspectRatio="none"
              viewBox="0 0 100 100"
            >
              <polygon
                className={styles.outlineShape}
                points={asPoints(inPerimeterOrder(tileCorners))}
              />
            </svg>
          )}
          {markerOutline.length === QUAD_CORNERS && (
            <svg
              aria-hidden="true"
              className={styles.outline}
              preserveAspectRatio="none"
              viewBox="0 0 100 100"
            >
              <polygon
                className={styles.markerShape}
                points={asPoints(markerOutline)}
              />
            </svg>
          )}
          {tileCorners.map((corner, index) => (
            <span
              className={styles.corner}
              // Corners have no identity of their own and are only ever
              // appended or cleared as a set, so the position is the key.
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
        </div>
      )}

      {failure !== null && (
        <p className={styles.failure} role="alert">
          {failure}
        </p>
      )}

      {(preview !== null || measurement !== null) && (
        <div className={styles.result}>
          {preview === null && measurement !== null && (
            // The fallback path has no homography, so there is no live
            // readout above the photo — the server's millimetres are the only
            // ones, and they belong on screen just as much.
            <span className={styles.millimetres}>
              {`${String(Math.round(measurement.short_mm))} × ${String(
                Math.round(measurement.long_mm),
              )} mm`}
            </span>
          )}
          <span className={styles.matched}>
            {matchedSize === null
              ? 'No catalogue size matches this measurement'
              : `Matches ${matchedSize}`}
          </span>
          {measurement !== null && !measurement.auto_detected && (
            // A tapped measurement is only as good as the taps, and the staff
            // member is the only one who knows how carefully they placed them.
            <span className={styles.method}>Measured from the corners you tapped.</span>
          )}
          {preview !== null && !preview.rectangular && (
            // **A warning, not a refusal.** This used to be a server rejection,
            // which stopped a measurement the staff member could see was right.
            // What it adds over the millimetres is the one thing no number
            // shows: that the marker may not be lying flat, which silently
            // scales everything.
            <span className={styles.method}>
              These corners do not measure as a rectangle — check the marker is flat on the tile
              and each corner is on the tile’s own corner.
            </span>
          )}
        </div>
      )}

      <div className={styles.actions}>
        {photo === null ? // Nothing to press down here until a photograph exists: the shutter
        // and the fallback both live on the viewfinder, under the thumb.
        null : matchedSize === null && homography === null ? (
          // **The only path that still uploads.** With no homography the
          // marker was not detected, so its corners are being tapped and the
          // server has to solve the geometry. Everything else is finished
          // here: the matrix came with the proposal and the corners are on
          // this screen, so a second upload would only repeat arithmetic that
          // is already done — over a showroom connection, on every adjustment.
          <button
            className={styles.measure}
            type="button"
            disabled={busy || !complete || markerId === ''}
            onClick={() => void measure()}
          >
            {busy ? 'Measuring…' : 'Measure'}
          </button>
        ) : matchedSize === null ? null : (
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
        {tapMarker && markerCorners.length > 0 && (
          // Takes back the last corner rather than clearing all four. A
          // mis-tap is one corner, and starting over for it is what makes
          // people accept a corner they know is slightly wrong.
          <button
            className={styles.back}
            type="button"
            disabled={busy}
            onClick={() => {
              const kept = collecting.slice(0, -1);
              if (tapMarker) setMarkerCorners(kept);
              else setTileCorners(kept);
              setMeasurement(null);
            }}
          >
            Undo corner
          </button>
        )}
        {photo !== null && (
          // Back to the viewfinder rather than straight to a second shutter:
          // the frame is worth composing, and a retake that fired the camera
          // immediately would take whatever the phone happened to be pointing
          // at when the last one was rejected.
          <button className={styles.back} type="button" disabled={busy} onClick={retake}>
            Retake
          </button>
        )}
        <button className={styles.back} type="button" onClick={onBack} disabled={busy}>
          Back
        </button>
      </div>
    </section>
  );
}
