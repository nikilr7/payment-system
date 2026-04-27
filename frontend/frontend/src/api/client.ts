import { v4 as uuidv4 } from 'uuid';
import type {
  Merchant,
  CreatePayoutRequest,
  CreatePayoutResponse,
  TopupRequest,
  TopupResponse,
} from '../types';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit & { idempotencyKey?: string } = {}
  ): Promise<T> {
    const { idempotencyKey, ...fetchOptions } = options;
    const url = `${this.baseUrl}${endpoint}`;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(fetchOptions.headers as Record<string, string>),
    };

    if (idempotencyKey) {
      headers['Idempotency-Key'] = idempotencyKey;
    }

    const response = await fetch(url, {
      ...fetchOptions,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `HTTP ${response.status}`);
    }

    return response.json() as Promise<T>;
  }

  async getMerchants(): Promise<Merchant[]> {
    return this.request<Merchant[]>('/merchants');
  }

  async createMerchant(name: string): Promise<Merchant> {
    return this.request<Merchant>('/merchants', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  async getMerchantDetails(merchantId: number): Promise<Merchant> {
    return this.request<Merchant>(`/merchants/${merchantId}`);
  }

  async topupMerchant(
    merchantId: number,
    amountPaise: number
  ): Promise<TopupResponse> {
    return this.request<TopupResponse>(`/merchants/${merchantId}/topup`, {
      method: 'POST',
      body: JSON.stringify({ amount_paise: amountPaise }),
    });
  }

  async createPayout(
    merchantId: number,
    amountPaise: number
  ): Promise<CreatePayoutResponse> {
    const idempotencyKey = uuidv4();
    return this.request<CreatePayoutResponse>('/payouts', {
      method: 'POST',
      body: JSON.stringify({
        merchant_id: merchantId,
        amount_paise: amountPaise,
      }),
      idempotencyKey,
    });
  }
}

export const apiClient = new ApiClient();
