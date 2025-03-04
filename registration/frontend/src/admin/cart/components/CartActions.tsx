import { Big } from "big.js";
import {
  Accessor,
  Component,
  createEffect,
  createMemo,
  createSignal,
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

  if (config.mqtt.supports_printing) {
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
            <span>Tender Cash</span>
          </ActionButton>
          <ActionButton
            class="is-warning"
            disabled={!canUseCard()}
            loading={loading()}
            setLoading={setLoading}
            keyboardShortcut={["Alt", "C"]}
            action={() => enableCardPayment(props.manager)}
          >
            <span class="icon">
              <i class="fas fa-credit-card"></i>
            </span>
            <span>Credit/Debit Card</span>
          </ActionButton>
        </div>
        <Show when={config.permissions.discount}>
          <div class="columns">
            <ActionButton
              class="is-link is-outlined"
              disabled={!canUseCard()}
              loading={loading()}
              setLoading={setLoading}
              action={() => createAndApplyDiscount(props.manager)}
            >
              <span class="icon">
                <i class="fas fa-gift"></i>
              </span>
              <span>Create Discount</span>
            </ActionButton>
          </div>
        </Show>
        <div class="columns">
          <ActionButton
            class="is-primary"
            disabled={!hasPrintableBadges()}
            loading={loading()}
            setLoading={setLoading}
            keyboardShortcut={["Control", "P"]}
            action={(ev) => {
              let holdingShift = false;
              if (ev instanceof KeyboardEvent || ev instanceof MouseEvent) {
                holdingShift = ev.shiftKey;
              }

              return printBadges(
                props.manager,
                printableBadgeIds(),
                setLoading,
                userSettings.userSettings().clear_cart_after_print,
                props.clearSearch,
                config.mqtt.supports_printing && !holdingShift
              );
            }}
          >
            <span class="icon">
              <i class="fas fa-print"></i>
            </span>
            <span>Print Badges</span>
          </ActionButton>
        </div>
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

async function enableCardPayment(manager: CartManager) {
  const resp = await manager.enableCardPayment();
  if (!resp.success) {
    alert(`Error enabling card payment: ${resp.reason}`);
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
