import {
  Accessor,
  Component,
  createEffect,
  createSignal,
  Setter,
} from "solid-js";

import { AttendeeSearch } from "./attendee-search";
import { Cart, CartManager } from "./cart";
import MqttClient from "./mqtt";
import { ScanPanel } from "./scan";

export const Onsite: Component<{
  mqtt: MqttClient;
  cartManager: CartManager;
  readyForNext: Accessor<boolean>;
  setReadyForNext: Setter<boolean>;
}> = (props) => {
  const [searchQuery, setSearchQuery] = createSignal<string>();

  createEffect(async () => {
    if (props.readyForNext()) {
      setSearchQuery("");
      await props.cartManager.clearCart();
      props.setReadyForNext(false);
    }
  });

  return (
    <div class="columns">
      <div class="column is-three-fifths is-narrow-tablet">
        <AttendeeSearch
          cartManager={props.cartManager}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
        />

        <ScanPanel
          gotScannedName={(name, birthday) => {
            const query = birthday ? `${name} birthday:${birthday}` : name;
            setSearchQuery(query);
          }}
          readyForNext={props.readyForNext}
          emitter={props.mqtt.emitter}
        />
      </div>

      <div class="column is-two-fifths is-narrow-tablet">
        <Cart
          cartManager={props.cartManager}
          clearSearch={() => setSearchQuery("")}
        />
      </div>
    </div>
  );
};
