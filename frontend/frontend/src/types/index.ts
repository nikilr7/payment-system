// Merchant types
export interface Merchant {
  merchant_id: number;
  name: string;
  balance_paise?: number;
  held_paise?: number;
  available_paise?: number;
}

// Payout types
export type PayoutStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface Payout {
  payout_id: number;
  merchant_id: number;
  amount: number;
  status: PayoutStatus;
  created_at: string;
  updated_at: string;
}

// API Response types
export interface ApiResponse<T> {
  data?: T;
  error?: string;
  message?: string;
}

export interface CreatePayoutRequest {
  merchant_id: number;
  amount_paise: number;
}

export interface CreatePayoutResponse {
  payout_id: number;
  status: PayoutStatus;
}

export interface TopupRequest {
  amount_paise: number;
}

export interface TopupResponse {
  merchant_id: number;
  topped_up_paise: number;
  new_balance_paise: number;
}
