import { useState } from 'react';
import './App.css';
import MerchantList from './pages/MerchantList';
import MerchantDashboard from './pages/MerchantDashboard';

function App() {
  const [selectedMerchantId, setSelectedMerchantId] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-800">
      <nav className="bg-slate-950 border-b border-slate-700 shadow-lg">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-3">
              <div className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-400">
                💰
              </div>
              <h1 className="text-xl font-bold text-white">Playto Payout Engine</h1>
            </div>
            <div className="text-sm text-slate-400">
              {selectedMerchantId ? '👤 Merchant Dashboard' : '📊 All Merchants'}
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {selectedMerchantId ? (
          <MerchantDashboard
            merchantId={selectedMerchantId}
            onBack={() => setSelectedMerchantId(null)}
          />
        ) : (
          <MerchantList
            onSelectMerchant={setSelectedMerchantId}
            onCreateNew={() => setShowForm(true)}
            refreshTrigger={showForm}
            onFormClose={() => setShowForm(false)}
          />
        )}
      </main>
    </div>
  );
}

export default App;
