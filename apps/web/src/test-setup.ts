/**
 * Test-environment setup, loaded by `vite.config.ts` before every test file.
 *
 * **Why the async timeout is raised.** Testing Library's `findBy*` and
 * `waitFor` default to a 1000ms budget, which is a statement about how long a
 * React update may take — and in this suite it is really a statement about how
 * long it takes *while twenty-nine test files run in parallel on one machine*.
 * Under that contention a perfectly correct update can miss the budget, and
 * the failure that results is about the scheduler rather than about the app:
 * the same assertion passes on its own, every time.
 *
 * Raising the budget does not hide a defect. A screen that never reaches the
 * state a test waits for still fails, just later; nothing is asserted that was
 * not asserted before. What it buys is a suite whose result means what it says
 * on a loaded laptop and in CI.
 */
import { configure } from '@testing-library/dom';

configure({ asyncUtilTimeout: 5000 });
