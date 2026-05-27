import { Accessor, createSignal, Setter } from "solid-js";

import { ApisUrls, CSRF_TOKEN } from "../../entrypoints/admin";
import MqttClient from "../mqtt";

const LOCK_NAME = "onsite-cart-update";

export class CartManager {
  private urls: ApisUrls;
  private mqtt: MqttClient;

  public cartEntries: Accessor<CartResponse | undefined>;
  private setCartEntries: Setter<CartResponse | undefined>;

  public pendingTransfers: Accessor<number[][]>;
  private setPendingTransfers: Setter<number[][]>;

  constructor(urls: ApisUrls, mqtt: MqttClient) {
    this.urls = urls;
    this.mqtt = mqtt;

    [this.cartEntries, this.setCartEntries] = createSignal<CartResponse>();
    [this.pendingTransfers, this.setPendingTransfers] = createSignal<
      number[][]
    >([], {
      equals: false,
    });

    this.mqtt.emitter.on("refresh", this.refreshCart.bind(this));
    this.mqtt.emitter.on("transfer", this.addPendingTransfer.bind(this));
    this.mqtt.emitter.on("waiverSigned", this.handleWaiverSigned.bind(this));
    this.mqtt.emitter.on("emergencyContactSaved", this.handleEmergencyContactSaved.bind(this));
  }

  close() {
    this.mqtt.emitter.off("refresh", this.refreshCart.bind(this));
    this.mqtt.emitter.off("transfer", this.addPendingTransfer.bind(this));
    this.mqtt.emitter.off("waiverSigned", this.handleWaiverSigned.bind(this));
    this.mqtt.emitter.off("emergencyContactSaved", this.handleEmergencyContactSaved.bind(this));
  }

  private async handleWaiverSigned(payload: unknown): Promise<void> {
    try {
      console.debug("waiverSigned MQTT event received", payload);
      const { orderReference, signature } = payload as {
        orderReference: string;
        signature: string;
      };
      const result = await this.makeRequest(
        this.urls.onsite_relay_waiver_signature,
        {
          method: "POST",
          body: JSON.stringify({ orderReference, signature }),
          headers: { "content-type": "application/json" },
        }
      );
      if (!result.success) {
        console.error("relay_waiver_signature failed", result);
      }
      await this.refreshCart();
    } catch (err) {
      console.error("handleWaiverSigned error", err);
    }
  }

  private async handleEmergencyContactSaved(payload: unknown): Promise<void> {
    try {
      console.debug("emergencyContactSaved MQTT event received", payload);
      const { orderReference, name, relationship, phone } = payload as {
        orderReference: string;
        name: string;
        relationship: string;
        phone: string;
      };
      const result = await this.makeRequest(
        this.urls.onsite_relay_emergency_contact,
        {
          method: "POST",
          body: JSON.stringify({ orderReference, name, relationship, phone }),
          headers: { "content-type": "application/json" },
        }
      );
      if (!result.success) {
        console.error("relay_emergency_contact failed", result);
      }
      await this.refreshCart();
    } catch (err) {
      console.error("handleEmergencyContactSaved error", err);
    }
  }

  private addPendingTransfer(payload: object | null) {
    const data = payload as { badgeIds: number[] };

    let pendingTransfers = this.pendingTransfers();
    pendingTransfers.push(data.badgeIds);
    this.setPendingTransfers(pendingTransfers);
  }

  public getNextTransfer(): number[] | undefined {
    let pendingTransfers = this.pendingTransfers();
    const nextTransfer = pendingTransfers.shift();
    this.setPendingTransfers(pendingTransfers);
    return nextTransfer;
  }

  private async makeRequest<T>(
    input: string | URL,
    init?: RequestInit
  ): Promise<FallibleRequest<T>> {
    const perform = async () => {
      console.debug("Making request", input);
      const resp = await fetch(input, {
        ...init,
        headers: { "x-csrftoken": CSRF_TOKEN, ...init?.headers },
      });
      const data = await resp.json();
      console.debug("Got response data", input, data);
      return data;
    };
    if ("locks" in navigator && navigator.locks) {
      console.debug("Aquiring cart update lock for request", input);
      return await navigator.locks.request(LOCK_NAME, perform);
    } else {
      console.warn("locks unavailable, session data might get out of sync!");
      return await perform();
    }
  }

  public async addCartId(id: number) {
    let url = new URL(this.urls.onsite_add_to_cart, window.location.href);
    url.searchParams.set("id", id.toString());

    await this.makeRequest(url, {
      method: "POST",
    });

    await this.refreshCart();
  }

  public async clearCart() {
    await this.makeRequest(this.urls.onsite_admin_clear_cart, {
      method: "POST",
    });

    this.setCartEntries(undefined);
  }

  public async refreshCart() {
    const data = await this.makeRequest<CartResponse>(
      this.urls.onsite_admin_cart
    );

    if (!data.success) {
      console.error("Failed to update cart", data);
      alert("Failed to update cart");
      window.location.reload();
      return;
    }

    this.setCartEntries(data);
  }

  public async removeBadge(id: number) {
    let url = new URL(this.urls.onsite_remove_from_cart, window.location.href);
    url.searchParams.set("id", id.toString());

    const data = await this.makeRequest(url, {
      method: "POST",
    });

    if (!data.success) {
      alert(`Error removing from cart: ${data.reason}`);
      return;
    }

    await this.refreshCart();
  }

  public async applyCashPayment(
    reference: string,
    total: string,
    tendered: string
  ): Promise<FallibleRequest<void>> {
    let url = new URL(
      this.urls.complete_cash_transaction,
      window.location.href
    );
    url.searchParams.set("reference", reference);
    url.searchParams.set("total", total);
    url.searchParams.set("tendered", tendered);

    const data = await this.makeRequest(url, {
      method: "POST",
    });

    return data;
  }

  public async enableCardPayment(
    fallback: boolean
  ): Promise<FallibleRequest<void>> {
    let url = new URL(this.urls.enable_payment, window.location.href);
    if (fallback) url.searchParams.set("fallback", "true");

    return await this.makeRequest(url);
  }

  public async markCheckedIn(
    orderReference: string,
    wristBandCount: number,
    cabinNumber: string,
    campsite: string,
    beforeClearingCart?: () => void,
  ): Promise<FallibleRequest<CheckedInResponse>> {
    const assignData = await this.makeRequest(this.urls.mark_checked_in, {
      method: "POST",
      body: JSON.stringify({
        orderReference: orderReference,
        wristBandCount: wristBandCount,
        cabinNumber: cabinNumber,
        campsite: campsite,
      })
    });

    if (!assignData.success) {
      return { success: false };
    }

    beforeClearingCart?.();
    await this.clearCart();

    return { success: true };
  }

  public async addBadgeNumber(
    orderReference: string,
    badgeNumber: number
  ): Promise<FallibleRequest<void>> {
    return this.makeRequest(this.urls.onsite_add_badge_number, {
      method: "POST",
      body: JSON.stringify({ orderReference, badgeNumber }),
    });
  }

  public async removeBadgeNumber(
    orderReference: string,
    badgeNumber: number
  ): Promise<FallibleRequest<void>> {
    return this.makeRequest(this.urls.onsite_remove_badge_number, {
      method: "POST",
      body: JSON.stringify({ orderReference, badgeNumber }),
    });
  }

  public async printBadges(
    ids: number[],
    clearCart: boolean = true,
    mqttPrint: boolean = false,
    beforeClearingCart?: () => void
  ): Promise<FallibleRequest<BadgePrintResponse>> {
    const assignData = await this.makeRequest(this.urls.assign_badge_number, {
      method: "POST",
      body: JSON.stringify(
        ids.map((id) => {
          return {
            id,
          };
        })
      ),
    });

    if (!assignData.success) {
      return { success: false };
    }

    let url = new URL(this.urls.onsite_print_badges, window.location.href);
    ids.forEach((id) => url.searchParams.append("id", id.toString()));

    const printData = await this.makeRequest<BadgePrintResponse>(url);

    if (printData.success && mqttPrint) {
      const url = new URL(printData.file, window.location.href);

      this.mqtt.publishPrintMessage(
        JSON.stringify({
          action: "print",
          url,
        })
      );

      if (clearCart) {
        beforeClearingCart?.();
        await this.clearCart();
      }
    }

    return printData;
  }

  public async clearBadgePrinted(id: number): Promise<FallibleRequest<void>> {
    let url = new URL(this.urls.onsite_print_clear, window.location.href);
    url.searchParams.set("id", id.toString());

    return await this.makeRequest(url, {
      method: "POST",
    });
  }

  public urlForBadge(id: number): string {
    let url = new URL(
      this.urls.registration_badge_change,
      window.location.href
    );
    url.pathname = url.pathname.replace("0", id.toString());
    return url.toString();
  }

  public viewWaiverUrl(orderReference: string): string {
    const url = new URL(this.urls.onsite_view_waiver, window.location.href);
    url.searchParams.set("reference", orderReference);
    return url.toString();
  }

  public alreadyInCart(id: number): boolean {
    return (
      this.cartEntries()?.result?.some((badge) => badge.id === id) || false
    );
  }

  public async createAndApplyDiscount(
    amount: string
  ): Promise<FallibleRequest<void>> {
    const formData = new FormData();
    formData.set("amount", amount);

    return await this.makeRequest(this.urls.onsite_create_discount, {
      method: "POST",
      body: formData,
    });
  }

  public async promptWaiver(
    orderReference: string
  ): Promise<FallibleRequest<void>> {
    let url = new URL(this.urls.onsite_prompt_waiver, window.location.href);
    url.searchParams.set("reference", orderReference);
    return await this.makeRequest(url);
  }

  public async promptEmergencyContact(
    orderReference: string
  ): Promise<FallibleRequest<void>> {
    const url = new URL(this.urls.onsite_prompt_emergency_contact, window.location.href);
    url.searchParams.set("reference", orderReference);
    return await this.makeRequest(url);
  }

  public async printReceipts(): Promise<FallibleRequest<void>> {
    if (!this.cartEntries()?.result) {
      return { success: true } as FallibleRequest<void>;
    }

    let url = new URL(this.urls.onsite_print_receipts, window.location.href);
    this.cartEntries()?.result?.forEach((badge) =>
      url.searchParams.append("reference", badge.reference)
    );

    return await this.makeRequest(url);
  }

  public async clearWaiver(
    orderReference: string
  ): Promise<FallibleRequest<void>> {
    const data = await this.makeRequest(this.urls.onsite_clear_waiver, {
      method: "POST",
      body: JSON.stringify({ orderReference }),
      headers: { "content-type": "application/json" },
    });
    if (!data.success) return data;
    await this.refreshCart();
    return { success: true };
  }

  public async transfer(terminal_id: number): Promise<FallibleRequest<void>> {
    if (!this.cartEntries()?.result) {
      return { success: true } as FallibleRequest<void>;
    }

    let url = new URL(
      this.urls.onsite_admin_transfer_cart,
      window.location.href
    );
    url.searchParams.append("terminal_id", terminal_id.toString());
    this.cartEntries()?.result?.forEach((badge) => {
      url.searchParams.append("badge_id", badge.id.toString());
    });

    const resp = await this.makeRequest(url);
    if (!resp.success) {
      return resp;
    }

    await this.clearCart();

    return { success: true } as FallibleRequest<void>;
  }
}

export type FallibleRequest<T> =
  | {
      success: false;
      reason?: string;
    }
  | ({ success: true } & T);

export interface CartResponse {
  charityDonation: string;
  order_id: number;
  orgDonation: string;
  reference: string;
  subtotal: string;
  total: string;
  total_discount: string;
  result: Badge[];
}

export interface Badge {
  id: number;
  abandoned: string;
  age: number;
  badgeName: string;
  badgeNumber?: number;
  firstName: string;
  lastName: string;
  holdType?: string;
  printed: boolean;
  effectiveLevel: EffectiveLevel;
  discount?: Discount;
  level_subtotal: string;
  level_discount: string;
  level_total: string;
  attendee_options: AttendeeOption[];
  reference: string;
  checkedInDate: string;
  wristBandCountPickedUp: number;
  cabinAssignment: string;
  campsiteAssignment: string;
  assignedBadgeNumbers: number[];
  staff?: Staff;
  waiverPdfUrl?: string | null;
  hasEmergencyContact?: boolean;
}

export interface EffectiveLevel {
  name: string;
  price: string;
}

export interface Discount {
  name: string;
  amount_off: string;
  percent_off: number;
  reason?: string;
}

export interface AttendeeOption {
  quantity: number;
  item: string;
  price: string;
  total: string;
  reason?: string;
  optionExtraType?: "int" | "bool" | "string" | "ShirtSizes";
  optionValue?: string;
}

export interface Staff {
  shirtSize: string;
}

export interface BadgePrintResponse {
  file: string;
  next: string;
  url: string;
}

export interface CheckedInResponse {
  success: boolean;
  message: string;
}
