import { Big } from "big.js";
import {
  Component,
  createMemo,
  For,
  Match,
  Show,
  Switch,
  useContext,
} from "solid-js";

import { ApisConfig } from "../../../entrypoints/admin";
import { ConfigContext } from "../../providers/config-provider";
import { AttendeeOption, CartManager, CartResponse } from "../cart-manager";
import { CartBadge } from "./CartBadge";

export const CartEntries: Component<{
  manager: CartManager;
  entries?: CartResponse;
}> = (props) => {
  const orderItems = createMemo(() =>
    props.entries?.result
      .flatMap((result) => {
        let options = result.attendee_options;
        if (result.discount) {
          let price;

          if (result.discount.percent_off > 0) {
            price = `-${result.discount.percent_off}%`;
          } else {
            price = `-$${result.discount.amount_off}`;
          }

          options.push({
            quantity: 1,
            price,
            item: `Discount ${result.discount.name}`,
            total: `-${cleanMoneyAmount(result.level_discount)}`,
            reason: result.discount.reason,
          });
        }
        return options;
      })
      .flat()
  );

  return (
    <>
      <Show when={(orderItems()?.length || 0) > 0}>
        <div class="panel-block">
          <table class="table is-fullwidth is-narrow">
            <thead>
              <tr>
                <th>Order Item</th>
                <th style="width: 20%;">Price</th>
              </tr>
            </thead>
            <tbody>
              <For each={orderItems()}>
                {(item) => (
                  <tr>
                    <AttendeeOptionDescription item={item} />
                    <td>
                      <span>{cleanMoneyAmount(item.total)}</span>
                    </td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </Show>

      <Show when={(props.entries?.result.length || 0) > 0}>
        <article class="panel-block is-block">
          <For each={props.entries!.result}>
            {(badge, index) => (
              <CartBadge
                data-index={index()}
                manager={props.manager}
                badge={badge}
              />
            )}
          </For>
        </article>
      </Show>

      <div class="panel-block">
        <table class="table is-fullwidth is-narrow">
          <tbody>
            <tr>
              <td>Subtotal:</td>
              <td style="width: 20%;">
                {cleanMoneyAmount(props.entries?.subtotal)}
              </td>
            </tr>
            <tr>
              <td>Discounts:</td>
              <td>{cleanMoneyAmount(props.entries?.total_discount)}</td>
            </tr>
            <tr>
              <td>Donation to Charity:</td>
              <td>{cleanMoneyAmount(props.entries?.charityDonation)}</td>
            </tr>
            <tr>
              <td>Donation to Convention:</td>
              <td>{cleanMoneyAmount(props.entries?.orgDonation)}</td>
            </tr>
            <tr class="has-text-weight-semibold">
              <td>Total:</td>
              <td>{cleanMoneyAmount(props.entries?.total)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
};

const AttendeeOptionDescription: Component<{ item: AttendeeOption }> = ({
  item,
}) => {
  const config = useContext(ConfigContext)!;

  return (
    <td>
      <div title={item.reason}>
        {`${item.quantity} × ${item.item} (${cleanMoneyAmount(item.price)}/ea)`}
        <Show
          when={
            item.optionExtraType === "ShirtSizes" ||
            item.optionExtraType == "bool"
          }
        >
          {` - `}
          <span class="has-text-weight-bold">
            <Switch>
              <Match when={item.optionExtraType === "ShirtSizes"}>
                {getShirtSizeName(config, item.optionValue)}
              </Match>
              <Match when={item.optionExtraType === "bool"}>
                {item.optionValue === "True" ? "Yes" : "No"}
              </Match>
            </Switch>
          </span>
        </Show>
      </div>
      <Show when={item.optionExtraType === "string"}>
        <div class="has-text-weight-bold">{item.optionValue}</div>
      </Show>
    </td>
  );
};

function getShirtSizeName(
  config: ApisConfig,
  optionValue?: string
): string | undefined {
  if (!optionValue) return;

  const sizeName = config.shirt_sizes.find(
    (entry) => entry.id === parseInt(optionValue, 10)
  )?.name;

  return sizeName || optionValue;
}

export function cleanMoneyAmount(input?: string): string {
  if (!input || input == "?") return "$0.00";

  let multi = 1;
  if (input.startsWith("-")) {
    multi = -1;
    input = input.substring(1);
  }

  if (input.startsWith("$")) {
    input = input.substring(1);
  }


  let parsed: Big;
  try {
    parsed = new Big(input).mul(multi);
  } catch (err) {
    console.error(`Could not parse money ${input}: ${err}`);
    return input;
  }

  return `$${parsed.toFixed(2)}`;
}
