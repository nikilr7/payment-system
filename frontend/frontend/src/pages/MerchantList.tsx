import { useState } from 'react';
import { useMerchants, useCreateMerchant } from '../hooks/useApi';
import type { Merchant } from '../types';

interface MerchantListProps {
  onSelectMerchant: (id: number) => void;
  onCreateNew: () => void;
  refreshTrigger: boolean;
  onFormClose: () => void;
}

export default function MerchantList({
  onSelectMerchant,
  onCreateNew,
  refreshTrigger,
  onFormClose,
}: MerchantListProps) {
  const { data: merchants, loading, error, refetch } = useMerchants();
  const { create, loading: creating, error: createError } = useCreateMerchant();
  const [openForm, setOpenForm] = useState(false);
  const [newMerchantName, setNewMerchantName] = useState('');

  const handleCreateMerchant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMerchantName.trim()) return;

    try {
      await create(newMerchantName);
      setNewMerchantName('');
      setOpenForm(false);
      onFormClose();
      refetch();
    } catch {
      // Error is handled in the hook
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
          <p className="mt-4 text-slate-300">Loading merchants...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold text-white">Merchants</h2>
        <button
          onClick={() => setOpenForm(true)}
          className="px-4 py-2 bg-gradient-to-r from-blue-500 to-cyan-500 text-white rounded-lg hover:from-blue-600 hover:to-cyan-600 transition font-semibold shadow-lg"
        >
          + Create Merchant
        </button>
      </div>

      {openForm && (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 shadow-lg">
          <h3 className="text-lg font-semibold text-white mb-4">New Merchant</h3>
          <form onSubmit={handleCreateMerchant} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Merchant Name
              </label>
              <input
                type="text"
                value={newMerchantName}
                onChange={(e) => setNewMerchantName(e.target.value)}
                placeholder="e.g., Freelancer A"
                className="w-full px-4 py-2 bg-slate-700 border border-slate-600 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                disabled={creating}
              />
            </div>
            {createError && (
              <p className="text-red-400 text-sm">{createError.message}</p>
            )}
            <div className="flex gap-3">
              <button
                type="submit"
                disabled={creating || !newMerchantName.trim()}
                className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-slate-600 transition font-medium"
              >
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setOpenForm(false);
                  setNewMerchantName('');
                }}
                className="flex-1 px-4 py-2 bg-slate-700 text-white rounded-lg hover:bg-slate-600 transition font-medium"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {error && (
        <div className="bg-red-900/30 border border-red-700 text-red-300 px-4 py-3 rounded-lg">
          Error loading merchants: {error.message}
        </div>
      )}

      {!merchants || merchants.length === 0 ? (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-12 text-center">
          <p className="text-slate-400">No merchants yet. Create one to get started!</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {merchants.map((merchant: Merchant) => (
            <div
              key={merchant.merchant_id}
              className="bg-slate-800 border border-slate-700 rounded-lg p-6 hover:border-slate-600 transition cursor-pointer shadow-lg hover:shadow-xl"
              onClick={() => onSelectMerchant(merchant.merchant_id)}
            >
              <div className="flex items-start justify-between mb-4">
                <h3 className="font-semibold text-lg text-white">{merchant.name}</h3>
                <span className="text-2xl">🏪</span>
              </div>
              <div className="space-y-2">
                <div>
                  <p className="text-xs text-slate-400">ID</p>
                  <p className="text-sm font-mono text-slate-300">#{merchant.merchant_id}</p>
                </div>
                <div className="pt-2 border-t border-slate-700">
                  <p className="text-xs text-slate-400">Balance</p>
                  <p className="text-l font-bold text-green-400">
                    ₹{((merchant.balance_paise || 0) / 100).toFixed(2)}
                  </p>
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectMerchant(merchant.merchant_id);
                }}
                className="mt-4 w-full px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded font-medium transition"
              >
                Open Dashboard →
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
