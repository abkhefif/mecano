import { useEffect, useState } from "react";
import api from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import type { Booking } from "../types";

const STATUS_OPTIONS = [
  { value: "", label: "Tous les statuts" },
  { value: "pending_acceptance", label: "En attente" },
  { value: "confirmed", label: "Confirmées" },
  { value: "check_in_done", label: "Check-in fait" },
  { value: "check_out_done", label: "Check-out fait" },
  { value: "validated", label: "Validées" },
  { value: "completed", label: "Terminées" },
  { value: "cancelled", label: "Annulées" },
  { value: "disputed", label: "Litiges" },
];

export function BookingsPage() {
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 20;

  useEffect(() => {
    setLoading(true);
    const params: Record<string, string | number> = { limit, offset };
    if (status) params.status = status;
    api.get("/admin/bookings", { params }).then((res) => {
      setBookings(res.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [status, offset]);

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Réservations</h1>

      <div className="mb-6">
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
          className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">ID</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Statut</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Véhicule</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Prix</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Commission</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Date</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-gray-500">Chargement...</td>
              </tr>
            ) : bookings.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-gray-500">Aucune réservation</td>
              </tr>
            ) : (
              bookings.map((b) => (
                <tr key={b.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 text-sm font-mono text-gray-600">{b.id.slice(0, 8)}</td>
                  <td className="px-6 py-4"><StatusBadge status={b.status} /></td>
                  <td className="px-6 py-4 text-sm text-gray-900">
                    {b.vehicle_brand} {b.vehicle_model} ({b.vehicle_year})
                  </td>
                  <td className="px-6 py-4 text-sm font-medium text-gray-900">{b.total_price || "—"}€</td>
                  <td className="px-6 py-4 text-sm text-gray-600">{b.commission_amount || "—"}€</td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {new Date(b.created_at).toLocaleDateString("fr-FR")}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex justify-between items-center mt-4">
        <button
          onClick={() => setOffset(Math.max(0, offset - limit))}
          disabled={offset === 0}
          className="px-4 py-2 text-sm font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
        >
          Précédent
        </button>
        <span className="text-sm text-gray-500">Page {Math.floor(offset / limit) + 1}</span>
        <button
          onClick={() => setOffset(offset + limit)}
          disabled={bookings.length < limit}
          className="px-4 py-2 text-sm font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
        >
          Suivant
        </button>
      </div>
    </div>
  );
}
