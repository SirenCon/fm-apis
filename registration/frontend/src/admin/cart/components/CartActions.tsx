import { Big } from "big.js";
import {
  Accessor,
  Component,
  createEffect,
  createMemo,
  createSignal,
  For,
  Setter,
  Show,
  useContext,
} from "solid-js";

import { SentryErrorBoundary } from "../../../entrypoints/admin";
import { ConfigContext } from "../../providers/config-provider";
import { UserSettingsContext } from "../../providers/user-settings-provider";
import { Badge, CartManager, CartResponse } from "../cart-manager";
import { ActionButton } from "./ActionButton";
import { CartActionsError } from "./CartActionsError";

const PRINTABLE_STATUS = new Set(["Paid", "Comp", "Staff", "Dealer"]);

export const CartActions: Component<{
  manager: CartManager;
  entries?: CartResponse;
  clearSearch(): void;
}> = (props) => {
  const config = useContext(ConfigContext)!;
  const userSettings = useContext(UserSettingsContext)!;

  const [loading, setLoading] = createSignal<boolean>(false);

  const [wristBandCount, setWristBandCount] = createSignal<number>(0);
  const [cabinNumber, setCabinNumber] = createSignal<string>("");
  const [campsite, setCampsite] = createSignal<string>("");
  const [badgeNumberInput, setBadgeNumberInput] = createSignal<string>("");

  const hasHold = createMemo(
    () =>
      props.entries?.result?.some((entry) => !!entry.holdType) ||
      isNaN(parseFloat(props?.entries?.total || ""))
  );

  const allNeedPayment = createMemo(
    () =>
      parseFloat(props.entries?.total || "") > 0 &&
      props.entries?.result.every(
        (entry) => !PRINTABLE_STATUS.has(entry.abandoned)
      )
  );

  const printableBadgeIds = createMemo(
    () =>
      props.entries?.result
        ?.filter((badge) => {
          const isPrintable =
            PRINTABLE_STATUS.has(badge.abandoned) &&
            !badge.holdType &&
            !badge.printed;

          return isPrintable;
        })
        ?.map((badge) => badge.id) || []
  );

  const allBadgesPaid = createMemo(
    () =>
      ((props.entries?.result?.length || 0) > 0 &&
        props.entries?.result?.every((badge) =>
          PRINTABLE_STATUS.has(badge.abandoned)
        )) ||
      false
  );

  if (config.terminals.selected?.features?.print_via_mqtt) {
    const autoPrintCheck = createAutoPrintCheck(printableBadgeIds);

    createEffect(async () => {
      if (!userSettings.userSettings().print_after_payment) return;

      if (autoPrintCheck(props.entries?.result || [])) {
        await printBadges(
          props.manager,
          printableBadgeIds(),
          setLoading,
          userSettings.userSettings().clear_cart_after_print,
          props.clearSearch,
          true
        );
      }
    });
  }

  const canTenderCash = () =>
    config.permissions.cash && !hasHold() && allNeedPayment();
  const canUseCard = () => !hasHold() && allNeedPayment();
  const hasPrintableBadges = () => printableBadgeIds()?.length > 0 || false;

  // Waiver: show prompt button when the order has been paid but no waiver is on file
  const hasWaiver = createMemo(
    () => props.entries?.result?.some((badge) => !!badge.waiverPdfUrl) ?? false
  );
  const waiverOrderReference = createMemo(
    () => props.entries?.result?.[0]?.reference
  );
  const canPromptWaiver = createMemo(
    () => allBadgesPaid() && !hasWaiver() && !!waiverOrderReference()
  );
  const hasEmergencyContact = createMemo(
    () => props.entries?.result?.some((badge) => badge.hasEmergencyContact) ?? false
  );
  const canPromptEmergencyContact = createMemo(
    () => allBadgesPaid() && !hasEmergencyContact() && !!waiverOrderReference()
  );

  const hasWaiverPdf = createMemo(() => {
    const url = props.manager.cartEntries()?.result?.find((b) => b.waiverPdfUrl)?.waiverPdfUrl;
    return !!url && !url.startsWith("local-dev://");
  });
  const viewWaiverUrl = createMemo(() => {
    const ref = waiverOrderReference();
    if (!ref || !hasWaiverPdf()) return null;
    return props.manager.viewWaiverUrl(ref);
  });

  return (
    <div class="control">
      <SentryErrorBoundary
        fallback={(err, reset) => (
          <CartActionsError
            err={err}
            reset={() => {
              setLoading(false);
              reset();
            }}
          />
        )}
      >
        <div class="columns">
          <Show
            when={config.terminals.selected?.features?.square_terminal}
            fallback={<div class="column"></div>}
          >
            <ActionButton
              class="is-link is-outlined"
              disabled={!allBadgesPaid()}
              loading={loading()}
              setLoading={setLoading}
              action={() => printReceipts(props.manager)}
            >
              <span class="icon">
                <i class="fas fa-receipt"></i>
              </span>
              <span>Receipt</span>
            </ActionButton>
          </Show>

          <Show
            when={
              config.permissions.cash &&
              config.terminals.selected?.features?.cashdrawer
            }
            fallback={<div class="column"></div>}
          >
            <ActionButton
              class="is-primary"
              disabled={!canTenderCash()}
              loading={loading()}
              setLoading={setLoading}
              keyboardShortcut={["Alt", "M"]}
              action={() => {
                if (props.entries) {
                  return attemptCashPayment(
                    props.manager,
                    props.entries.reference,
                    props.entries.total
                  );
                }
              }}
            >
              <span class="icon">
                <i class="fas fa-money-bill-alt"></i>
              </span>
              <span>Cash</span>
            </ActionButton>
          </Show>

          <Show
            when={APIS_CONFIG.terminals.selected?.features?.payment_type}
            fallback={<div class="column"></div>}
          >
            <ActionButton
              class="is-primary"
              disabled={!canUseCard()}
              loading={loading()}
              setLoading={setLoading}
              keyboardShortcut={["Alt", "C"]}
              action={() => enableCardPayment(props.manager, false)}
              altAction={() => enableCardPayment(props.manager, true)}
            >
              <span class="icon">
                <i class="fas fa-credit-card"></i>
              </span>
              <span>Card</span>
            </ActionButton>
          </Show>
        </div>

        <div class="columns">
          <Show
            when={config.permissions.discount}
            fallback={<div class="column"></div>}
          >
            <ActionButton
              class="is-warning is-outlined"
              disabled={!canUseCard()}
              loading={loading()}
              setLoading={setLoading}
              action={() => createAndApplyDiscount(props.manager)}
            >
              <span class="icon">
                <i class="fas fa-gift"></i>
              </span>
              <span>Discount</span>
            </ActionButton>
          </Show>

          <ActionButton
            class="is-link"
            disabled={!allBadgesPaid()}
            loading={loading()}
            setLoading={setLoading}
            action={(ev) => {
              return markCheckedIn(
                props.manager,
                props.entries?.result,
                wristBandCount(),
                cabinNumber(),
                campsite(),
                setLoading,
                userSettings.userSettings().clear_cart_after_print,
                props.clearSearch,
              )
            }}
          >
            <span class="icon">
              <i class="fas fa-print"></i>
            </span>
            <span>Check In</span>
          </ActionButton>
        </div>

        {/* Waiver row */}
        <div class="columns">
          <Show when={canPromptWaiver()}>
            <ActionButton
              class="is-warning"
              disabled={false}
              loading={loading()}
              setLoading={setLoading}
              action={() => promptWaiver(props.manager, waiverOrderReference()!)}
            >
              <span class="icon">
                <i class="fas fa-file-signature"></i>
              </span>
              <span>Prompt For Waiver</span>
            </ActionButton>
          </Show>

          <Show when={allBadgesPaid() && !hasWaiver()}>
            <div class="column is-narrow is-align-self-center">
              <span class="tag is-warning is-medium">
                <span class="icon"><i class="fas fa-triangle-exclamation"></i></span>
                <span>No waiver on file</span>
              </span>
            </div>
          </Show>

          <Show when={allBadgesPaid() && hasWaiver()}>
            <div class="column is-narrow is-align-self-center">
              <div class="tags has-addons" style="margin-bottom: 0">
                <span class="tag is-success is-medium">
                  <span class="icon"><i class="fas fa-file-circle-check"></i></span>
                  <span>Waiver signed</span>
                </span>
                <Show when={hasWaiverPdf()}>
                  <a class="tag is-link is-medium" href={viewWaiverUrl()!} target="_blank" rel="noopener">
                    View PDF
                  </a>
                </Show>
              </div>
            </div>
            <ActionButton
              class="is-danger is-light"
              disabled={false}
              loading={loading()}
              setLoading={setLoading}
              action={() => clearWaiver(props.manager, waiverOrderReference()!)}
            >
              <span class="icon"><i class="fas fa-trash"></i></span>
              <span>Clear Waiver</span>
            </ActionButton>
          </Show>
        </div>

        {/* Emergency contact row */}
        <div class="columns">
          <Show when={canPromptEmergencyContact()}>
            <ActionButton
              class="is-warning"
              disabled={false}
              loading={loading()}
              setLoading={setLoading}
              action={() => props.manager.promptEmergencyContact(waiverOrderReference()!)}
            >
              <span class="icon">
                <i class="fas fa-user-shield"></i>
              </span>
              <span>Collect Emergency Contact</span>
            </ActionButton>
          </Show>

          <Show when={allBadgesPaid() && !hasEmergencyContact()}>
            <div class="column is-narrow is-align-self-center">
              <span class="tag is-warning is-medium">
                <span class="icon"><i class="fas fa-triangle-exclamation"></i></span>
                <span>No emergency contact on file</span>
              </span>
            </div>
          </Show>

          <Show when={allBadgesPaid() && hasEmergencyContact()}>
            <div class="column is-narrow is-align-self-center">
              <span class="tag is-success is-medium">
                <span class="icon"><i class="fas fa-circle-check"></i></span>
                <span>Emergency contact on file</span>
              </span>
            </div>
          </Show>
        </div>

        <div class="columns">
          <div class="column">
            <p class="control is-expanded">
              <label class="col-sm-3 control-label">Wristbands</label>
              <input
                type="number"
                name="wristBandCount"
                class="input"
                placeholder="# of wrist bands picked up"
                required
                value={wristBandCount()}
                onChange={(e) => setWristBandCount(e.currentTarget.value)}
              />
            </p>
          </div>

          <div class="column">
            <p class="control is-expanded">
              <label class="col-sm-3 control-label">Cabin #</label>
              <input
                type="text"
                name="cabinNumber"
                class="input"
                placeholder="Cabin #"
                value={cabinNumber()}
                onChange={(e) => setCabinNumber(e.currentTarget.value)}
              />
            </p>
          </div>

          <div class="column">
            <p class="control is-expanded">
              <label class="col-sm-3 control-label">Campsite</label>
              <input
                type="text"
                name="campSite"
                class="input"
                placeholder="Campsite"
                value={campsite()}
                onChange={(e) => setCampsite(e.currentTarget.value)}
              />
            </p>
          </div>

        </div>

        <div class="columns">
          <div class="column">
            <p class="control is-expanded">
              <label class="col-sm-3 control-label">Badge #</label>
              <input
                type="number"
                name="badgeNumberInput"
                class="input"
                placeholder="Enter badge number"
                value={badgeNumberInput()}
                onInput={(e) => setBadgeNumberInput(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    const n = parseInt(badgeNumberInput(), 10);
                    const reference = props.entries?.result?.[0]?.reference;
                    if (!isNaN(n) && reference) {
                      props.manager.addBadgeNumber(reference, n).then((resp) => {
                        if (resp.success) {
                          props.manager.refreshCart();
                          setBadgeNumberInput("");
                        } else {
                          alert(`Error adding badge number: ${(resp as any).reason ?? "Unknown error"}`);
                        }
                      });
                    }
                  }
                }}
              />
            </p>
          </div>
          <div class="column is-narrow" style="display: flex; align-items: flex-end;">
            <button
              class="button is-info"
              disabled={badgeNumberInput() === "" || isNaN(parseInt(badgeNumberInput(), 10))}
              onClick={() => {
                const n = parseInt(badgeNumberInput(), 10);
                const reference = props.entries?.result?.[0]?.reference;
                if (!isNaN(n) && reference) {
                  props.manager.addBadgeNumber(reference, n).then((resp) => {
                    if (resp.success) {
                      props.manager.refreshCart();
                      setBadgeNumberInput("");
                    } else {
                      alert(`Error adding badge number: ${(resp as any).reason ?? "Unknown error"}`);
                    }
                  });
                }
              }}
            >
              Add
            </button>
          </div>
        </div>

        <Show when={(props.entries?.result?.[0]?.assignedBadgeNumbers?.length ?? 0) > 0}>
          <div class="columns">
            <div class="column">
              <div class="tags">
                <For each={props.entries?.result?.[0]?.assignedBadgeNumbers ?? []}>
                  {(num) => (
                    <span class="tag is-info is-medium">
                      #{num}
                      <button
                        class="delete is-small"
                        onClick={() => {
                          const reference = props.entries?.result?.[0]?.reference;
                          if (reference) {
                            props.manager.removeBadgeNumber(reference, num).then((resp) => {
                              if (resp.success) {
                                props.manager.refreshCart();
                              } else {
                                alert(`Error removing badge number: ${(resp as any).reason ?? "Unknown error"}`);
                              }
                            });
                          }
                        }}
                      />
                    </span>
                  )}
                </For>
              </div>
            </div>
          </div>
        </Show>
      </SentryErrorBoundary>
    </div>
  );
};

async function attemptCashPayment(
  manager: CartManager,
  reference: string,
  total: string
) {
  const totalAmount = new Big(total);

  const tendered = prompt("Enter tendered amount");
  if (!tendered) return;

  let tenderedAmount: Big;
  try {
    tenderedAmount = new Big(tendered);
  } catch (err) {
    alert("Invalid amount.");
    return;
  }

  if (tenderedAmount.lt(totalAmount)) {
    alert("Insufficient payment, split tender unsupported.");
    return;
  }

  let change = tenderedAmount.sub(totalAmount);

  const resp = await manager.applyCashPayment(reference, total, tendered);
  if (resp.success) {
    manager.refreshCart();
  } else {
    alert(`Error posting cash transaction: ${resp.reason}`);
    return;
  }

  alert(`Change: $${change.toFixed(2)}`);
}

async function createAndApplyDiscount(manager: CartManager) {
  const discountAmount = prompt(
    "Enter discount amount, starting with either $ or %"
  );
  if (!discountAmount) return;

  const resp = await manager.createAndApplyDiscount(discountAmount);
  if (resp.success) {
    manager.refreshCart();
  } else {
    alert(`Error creating discount: ${resp.reason}`);
  }
}

async function enableCardPayment(manager: CartManager, fallback: boolean) {
  const resp = await manager.enableCardPayment(fallback);
  if (!resp.success) {
    alert(`Error enabling card payment: ${resp.reason}`);
  }
}

async function markCheckedIn(
  manager: CartManager,
  badges: string,
  wristBandCount: number,
  cabinNumber: string,
  campsite: string,
  setLoading: Setter<boolean>,
  clearCart: boolean,
  clearSearch: () => void,
) {
  if (badges.length > 1) {
    alert("Only one order can be in the cart for checkin");
    return;
  }

  const orderReference = badges[0].reference;

  setLoading(true);
  const resp = await manager.markCheckedIn(
    orderReference,
    wristBandCount,
    cabinNumber,
    campsite,
    clearSearch,
  );
  setLoading(false);

  if (!resp.success) {
    alert(`Error checking in: ${resp.message}`);
    return;
  }
}

async function printBadges(
  manager: CartManager,
  ids: number[],
  setLoading: Setter<boolean>,
  clearCart: boolean,
  clearSearch: () => void,
  mqttPrint: boolean
) {
  setLoading(true);
  const resp = await manager.printBadges(
    ids,
    clearCart,
    mqttPrint,
    clearSearch
  );
  setLoading(false);

  if (!resp.success) {
    alert(`Error printing badges: ${resp.reason}`);
    return;
  }

  if (!mqttPrint) {
    window.open(resp.url, "badge");
  }
}

async function promptWaiver(manager: CartManager, orderReference: string) {
  const resp = await manager.promptWaiver(orderReference);
  if (!resp.success) {
    alert(`Error prompting for waiver: ${resp.reason}`);
  }
}

async function clearWaiver(manager: CartManager, orderReference: string) {
  const resp = await manager.clearWaiver(orderReference);
  if (!resp.success) {
    alert(`Error clearing waiver: ${resp.reason}`);
  }
}

async function printReceipts(manager: CartManager) {
  const resp = await manager.printReceipts();

  if (!resp.success) {
    alert(`Error printing receipts: ${resp.reason}`);
  }
}

function createAutoPrintCheck(
  printableBadgeIds: Accessor<number[]>
): (currentBadges: Badge[]) => boolean {
  let previousBadges: Badge[] = [];

  return function (nextBadges: Badge[]): boolean {
    let currentBadges = previousBadges;
    previousBadges = nextBadges;

    if (nextBadges.length === 0 || currentBadges.length !== nextBadges.length) {
      return false;
    }

    const printableIds = printableBadgeIds();

    for (let i = 0; i < currentBadges.length; i += 1) {
      const prev = currentBadges[i];
      const curr = nextBadges[i];

      if (!printableIds.includes(curr.id)) {
        return false;
      }

      if (
        prev.id !== curr.id ||
        curr.abandoned === prev.abandoned ||
        curr.abandoned !== "Paid"
      ) {
        return false;
      }
    }

    return true;
  };
}
