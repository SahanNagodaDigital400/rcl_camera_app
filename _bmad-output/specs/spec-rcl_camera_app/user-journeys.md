# User Journeys

Named-persona narratives the product enables. Referenced from `SPEC.md`'s Assumptions and from `functional-requirements.md`'s capability mapping.

## UJ-1. Kasun identifies an unlabelled tile mid-sale

*Narrated from the brief's described flow, not a user-provided session — see `SPEC.md` Assumptions.*

- **Persona + context:** Kasun, a showroom sales associate, is helping a customer who's brought in a leftover tile from a renovation and wants three more boxes of the same one.
- **Entry state:** Already authenticated — his session has persisted through the shift. On the showroom floor, PWA installed to his home screen.
- **Path:** Opens the app → taps Scan → on-screen framing guide helps him fill the frame with the tile face → captures the photo → adjusts the crop selection to the tile face and confirms → brief processing → results screen shows three candidates, each with its reference image, cleaned code, and size/design.
- **Climax:** The top card's reference image visually matches the tile in his hand within a second or two of looking at it — he doesn't need to recognize a code, just recognize a picture.
- **Resolution:** He reads the code to the customer and proceeds with the order. The scan is saved to his history.
- **Edge case:** None of the three candidates look right — he retakes the photo with better framing, or falls back to asking a colleague (this is what the Fallback Rate success signal measures).
- **Capability mapping:** CAP-2 (capture, crop, quality guidance, ranked results, history).

## UJ-2. Nadeesha adds a new tile range the day it arrives

*Narrated from the brief's described flow, not a user-provided session — see `SPEC.md` Assumptions.*

- **Persona + context:** Nadeesha, an operations admin, receives a new tile range and needs it identifiable before it hits the showroom floor.
- **Entry state:** Authenticated as admin, in the catalogue management screen.
- **Path:** Opens Add Product → enters the product code → captures or uploads one or more reference images → saves.
- **Climax:** She runs a test scan against the physical sample in the same session — the new product appears as a match. No ticket filed with engineering, no wait for the next data import.
- **Resolution:** The catalogue is current; any staff member can now identify that product.
- **Edge case:** The reference image she uploaded is blurry or badly lit — it's flagged as below the quality threshold so it can be re-shot before it degrades future match quality.
- **Capability mapping:** CAP-4 (add product, automatic re-index).

## UJ-3. Ruwan deactivates a departing staff member

Ruwan, IT admin, processes an exit on someone's last day: opens the user list, deactivates the account, and their session dies immediately — even if they're still logged in on their phone.

- **Capability mapping:** CAP-3 (deactivate/delete user, immediate session revocation).
