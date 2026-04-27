import { useState, useEffect } from 'react';
import {
  useMerchantDetails,
  useTopupMerchant,
  useCreatePayout,
} from '../hooks/useApi';

interface MerchantDashboardProps {
  merchantId: number;
  onBack: () => void;
}

const formatPaise = (paise: number | undefined) => {
  if (!paise) return '₹0.00';
  return `₹${(paise / 100).toFixed(2)}`;
};

export default function MerchantDashboard({
  merchantId,
  onBack,
}: MerchantDashboardProps) {
  const { data: merchant, loading, error, refetch } = useMerchantDetails(
    merchantId
  );
  const { topup, loading: topupLoading, error: topupError } = useTopupMerchant();
  const { create: createPayout, loading: payoutLoading, error: payoutError } = useCreatePayout();

  const [topupAmount, setTopupAmount] = useState('');
  const [payoutAmount, setPayoutAmount] = useState('');
  const [showTopupForm, setShowTopupForm] = useState(false);
  const [showPayoutForm, setShowPayoutForm] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleTopup = async (e: React.FormEvent) => {
    e.preventDefault();
    const amount = parseInt(topupAmount);
    if (!amount || amount <= 0) return;

    try {
      await topup(merchantId, amount);
      setTopupAmount('');
      setShowTopupForm(false);
      setMessage({ type: 'success', text: `Topup of ₹${(amount / 100).toFixed(2)} successful!` });
      setTimeout(() => setMessage(null), 3000);
      refetch();
    } catch {
      setMessage({ type: 'error', text: topupError?.message || 'Topup failed' });
    }
  };

  const handleCreatePayout = async (e: React.FormEvent) => {
    e.preventDefault();
    const amount = parseInt(payoutAmount);
    if (!amount || amount <= 0) return;

    try {
      await createPayout(merchantId, amount);
      setPayoutAmount('');
      setShowPayoutForm(false);
      setMessage({ type: 'success', text: `Payout of ₹${(amount / 100).toFixed(2)} initiated!` });
      setTimeout(() => setMessage(null), 3000);
      refetch();
    } catch {
      setMessage({ type: 'error', text: payoutError?.message || 'Payout failed' });
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
          <p className="mt-4 text-slate-300">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  if (error || !merchant) {
    return (
      <div className="bg-red-900/30 border border-red-700 text-red-300 px-6 py-4 rounded-lg">
        Error loading merchant: {error?.message || 'Unknown error'}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <button
        onClick={onBack}
        className="px-4 py-2 text-slate-300 hover:text-white transition flex items-center gap-2"
      >
        ← Back to Merchants
      </button>

      {message && (
        <div
          className={`px-6 py-4 rounded-lg ${
            message.type === 'success'
              ? 'bg-green-900/30 border border-green-700 text-green-300'
              : 'bg-red-900/30 border border-red-700 text-red-300'
          }`}
        >
          {message.text}
        </div>
      )}

      <div className="bg-gradient-to-r from-slate-800 to-slate-700 border border-slate-600 rounded-lg p-8 shadow-lg">
        <div className="flex justify-between items-start mb-6">
          <div>
            <h2 className="text-2xl font-bold text-white">{merchant.name}</h2>
            <p className="text-slate-400 mt-1">ID: #{merchant.merchant_id}</p>
          </div>
          <span className="text-4xl">🏪</span>
        </div>

        <div className="grid md:grid-cols-3 gap-4 mb-6">
          <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-600">
            <p className="text-slate-400 text-sm mb-1">Total Balance</p>
            <p className="text-2xl font-bold text-cyan-400">
              {formatPaise(merchant.balance_paise)}
            </p>
          </div>
          <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-600">
            <p className="text-slate-400 text-sm mb-1">Held/Processing</p>
            <p className="text-2xl font-bold text-orange-400">
              {formatPaise(merchant.held_paise)}
            </p>
          </div>
          <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-600">
            <p className="text-slate-400 text-sm mb-1">Available for Payout</p>
            <p className="text-2xl font-bold text-green-400">
              {formatPaise(merchant.available_paise)}
            </p>
          </div>
        </div>

        <div className="flex gap-3">
          <button
            onClick={() => setShowTopupForm(!showTopupForm)}
            className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg transition font-medium"
          >
            + Topup Balance
          </button>
          <button
            onClick={() => setShowPayoutForm(!showPayoutForm)}
            disabled={!merchant.available_paise || merchant.available_paise <= 0}
            className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 text-white rounded-lg transition font-medium"
          >
            → Request Payout
          </button>
        </div>
      </div>

      {showTopupForm && (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-lg">
          <h3 className="text-lg font-semibold text-white mb-4">Topup Balance</h3>
          <form onSubmit={handleTopup} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Amount (Paise) — 100 paise = ₹1
              </label>
              <input
                type="number"
                value={topupAmount}
                onChange={(e) => setTopupAmount(e.target.value)}
                placeholder="e.g., 10000 (for ₹100)"
                className="w-full px-4 py-2 bg-slate-700 border border-slate-600 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-green-500"
                disabled={topupLoading}
                min="1"
              />
            </div>
            {topupError && (
              <p className="text-red-400 text-sm">{topupError.message}</p>
            )}
            <div className="flex gap-3">
              <button
                type="submit"
                disabled={topupLoading || !topupAmount}
                className="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-slate-600 transition font-medium"
              >
                {topupLoading ? 'Processing...' : 'Topup'}
              </button>
              <button
                type="button"
                onClick={() => setShowTopupForm(false)}
                className="flex-1 px-4 py-2 bg-slate-700 text-white rounded-lg hover:bg-slate-600 transition font-medium"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {showPayoutForm && (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-lg">
          <h3 className="text-lg font-semibold text-white mb-4">Request Payout</h3>
          <form onSubmit={handleCreatePayout} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Amount (Paise) — 100 paise = ₹1
              </label>
              <input
                type="number"
                value={payoutAmount}
                onChange={(e) => setPayoutAmount(e.target.value)}
                placeholder={`Max: ${formatPaise(merchant.available_paise)}`}
                className="w-full px-4 py-2 bg-slate-700 border border-slate-600 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                disabled={payoutLoading}
                min="1"
                max={merchant.available_paise}
              />
              <p className="text-xs text-slate-400 mt-2">
                Available: {formatPaise(merchant.available_paise)}
              </p>
            </div>
            {payoutError && (
              <p className="text-red-400 text-sm">{payoutError.message}</p>
            )}
            <div className="flex gap-3">
              <button
                type="submit"
                disabled={payoutLoading || !payoutAmount}
                className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-slate-600 transition font-medium"
              >
                {payoutLoading ? 'Processing...' : 'Request Payout'}
              </button>
              <button
                type="button"
                onClick={() => setShowPayoutForm(false)}
                className="flex-1 px-4 py-2 bg-slate-700 text-white rounded-lg hover:bg-slate-600 transition font-medium"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-lg">
        <h3 className="text-lg font-semibold text-white mb-4">How It Works</h3>
        <ul className="space-y-2 text-sm text-slate-300">
          <li className="flex gap-3">
            <span className="text-cyan-400">•</span>
            <span><strong>Topup:</strong> Add funds to your merchant account</span>
          </li>
          <li className="flex gap-3">
            <span className="text-blue-400">•</span>
            <span><strong>Payout:</strong> Request withdrawal to your bank account</span>
          </li>
          <li className="flex gap-3">
            <span className="text-orange-400">•</span>
            <span><strong>Held:</strong> Funds in payouts currently processing</span>
          </li>
          <li className="flex gap-3">
            <span className="text-green-400">•</span>
            <span><strong>Available:</strong> Balance − Held (can request payout)</span>
          </li>
        </ul>
      </div>
    </div>
  );
}
