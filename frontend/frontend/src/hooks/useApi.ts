import { useState, useEffect, useCallback, useRef } from 'react';
import { apiClient } from '../api/client';
import type { Merchant } from '../types';

interface UseAsyncOptions {
  onError?: (error: Error) => void;
}

export function useAsync<T>(
  asyncFn: () => Promise<T>,
  deps: unknown[],
  options: UseAsyncOptions = {}
) {
  const [data, setData]       = useState<T | null>(null);
  const [error, setError]     = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  // Keep latest asyncFn and options in refs — never stale, never cause re-renders
  const asyncFnRef = useRef(asyncFn);
  const optionsRef = useRef(options);
  asyncFnRef.current = asyncFn;
  optionsRef.current = options;

  const execute = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await asyncFnRef.current();
      setData(result);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      optionsRef.current.onError?.(error);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    execute();
  }, [execute]);

  return { data, error, loading, refetch: execute };
}

export function useMerchants() {
  return useAsync(() => apiClient.getMerchants(), []);
}

export function useMerchantDetails(merchantId: number | null) {
  return useAsync(
    () => {
      if (!merchantId) throw new Error('Merchant ID required');
      return apiClient.getMerchantDetails(merchantId);
    },
    [merchantId],
    { onError: () => {} }
  );
}

export function useCreateMerchant() {
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<Error | null>(null);

  const create = useCallback(async (name: string) => {
    setLoading(true);
    setError(null);
    try {
      return await apiClient.createMerchant(name);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, []);

  return { create, loading, error };
}

export function useTopupMerchant() {
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<Error | null>(null);

  const topup = useCallback(async (merchantId: number, amountPaise: number) => {
    setLoading(true);
    setError(null);
    try {
      return await apiClient.topupMerchant(merchantId, amountPaise);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, []);

  return { topup, loading, error };
}

export function useCreatePayout() {
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<Error | null>(null);

  const create = useCallback(async (merchantId: number, amountPaise: number) => {
    setLoading(true);
    setError(null);
    try {
      return await apiClient.createPayout(merchantId, amountPaise);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, []);

  return { create, loading, error };
}
