import { useEffect, useState } from "react";
import api from "../api/client";
import type { Stats } from "../types";

const STAT_CARDS = [
  { key: "total_users", label: "Utilisateurs", icon: "👥", color: "bg-blue-50 text-blue-700" },
  { key: "total_mechanics", label: "Mécaniciens", icon: "🔧", color: "bg-green-50 text-green-700" },
  { key: "total_buyers", label: "Acheteurs", icon: "🛒", color: "bg-purple-50 text-purple-700" },
  { key: "total_bookings", label: "Réservations", icon: "📋", color: "bg-indigo-50 text-indigo-700" },
  { key: "total_revenue", label: "Revenus total", icon: "💰", color: "bg-emerald-50 text-emerald-700", suffix: "€" },
  { key: "pending_verifications", label: "Vérifications en attente", icon: "🛡️", color: "bg-yellow-50 text-yellow-700" },
  { key: "active_disputes", label: "Litiges actifs", icon: "⚠️", color: "bg-red-50 text-red-700" },
] as const;

export function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/admin/stats").then((res) => {
      setStats(res.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-8">Dashboard</h1>

      {loading ? (
        <div className="text-gray-500">Chargement...</div>
      ) : stats ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {STAT_CARDS.map((card) => {
            const value = stats[card.key as keyof Stats];
            return (
              <div key={card.key} className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <div className="flex items-center gap-4">
                  <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-xl ${card.color}`}>
                    {card.icon}
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">{card.label}</p>
                    <p className="text-2xl font-bold text-gray-900">
                      {typeof value === "number" ? value.toLocaleString("fr-FR") : value}
                      {"suffix" in card ? card.suffix : ""}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-red-500">Erreur de chargement</div>
      )}
    </div>
  );
}
