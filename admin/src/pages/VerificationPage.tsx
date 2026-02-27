import { useEffect, useState } from "react";
import api from "../api/client";
import { ImageModal } from "../components/ImageModal";
import type { PendingMechanic } from "../types";

export function VerificationPage() {
  const [mechanics, setMechanics] = useState<PendingMechanic[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [imageModal, setImageModal] = useState<{ url: string; alt: string } | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState("");

  const fetchMechanics = () => {
    setLoading(true);
    api.get("/admin/mechanics/pending-verification").then((res) => {
      setMechanics(res.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  };

  useEffect(() => { fetchMechanics(); }, []);

  const handleVerify = async (id: string, approved: boolean) => {
    setActionLoading(id);
    try {
      await api.patch(`/admin/mechanics/${id}/verify`, { approved });
      setMechanics((prev) => prev.filter((m) => m.id !== id));
      setSelectedId(null);
      setSuccessMsg(approved ? "Mécanicien approuvé" : "Mécanicien rejeté");
      setTimeout(() => setSuccessMsg(""), 3000);
    } catch {
      alert("Erreur lors de la vérification");
    } finally {
      setActionLoading(null);
    }
  };

  const selected = mechanics.find((m) => m.id === selectedId);

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Vérification des mécaniciens</h1>
      <p className="text-gray-500 mb-6">
        {mechanics.length} mécanicien{mechanics.length !== 1 ? "s" : ""} en attente de vérification
      </p>

      {successMsg && (
        <div className="mb-4 bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg">
          {successMsg}
        </div>
      )}

      {loading ? (
        <div className="text-gray-500">Chargement...</div>
      ) : mechanics.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 p-12 text-center">
          <p className="text-gray-500 text-lg">Aucune vérification en attente</p>
        </div>
      ) : (
        <div className="flex gap-6">
          {/* List */}
          <div className="w-1/2">
            <div className="bg-white rounded-xl shadow-sm border border-gray-100 divide-y divide-gray-100">
              {mechanics.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setSelectedId(m.id)}
                  className={`w-full text-left px-6 py-4 hover:bg-gray-50 transition-colors ${
                    selectedId === m.id ? "bg-blue-50 border-l-4 border-l-blue-500" : ""
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-semibold text-gray-900">
                        {m.first_name || ""} {m.last_name || ""}
                      </p>
                      <p className="text-sm text-gray-500">{m.email}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-gray-500">{m.city}</p>
                      <p className="text-xs text-gray-400">
                        {new Date(m.created_at).toLocaleDateString("fr-FR")}
                      </p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Detail panel */}
          <div className="w-1/2">
            {selected ? (
              <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-lg font-bold text-gray-900 mb-1">
                  {selected.first_name || ""} {selected.last_name || ""}
                </h2>
                <p className="text-sm text-gray-500 mb-6">{selected.email} - {selected.city}</p>

                <div className="grid grid-cols-2 gap-4 mb-6">
                  <div>
                    <p className="text-sm font-medium text-gray-700 mb-2">Pièce d'identité</p>
                    {selected.identity_document_url ? (
                      <img
                        src={selected.identity_document_url}
                        alt="Pièce d'identité"
                        className="w-full h-48 object-cover rounded-lg border border-gray-200 cursor-pointer hover:opacity-80 transition-opacity"
                        onClick={() => setImageModal({ url: selected.identity_document_url!, alt: "Pièce d'identité" })}
                      />
                    ) : (
                      <div className="w-full h-48 bg-gray-100 rounded-lg flex items-center justify-center text-gray-400">
                        Non fourni
                      </div>
                    )}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-700 mb-2">Selfie avec pièce d'identité</p>
                    {selected.selfie_with_id_url ? (
                      <img
                        src={selected.selfie_with_id_url}
                        alt="Selfie"
                        className="w-full h-48 object-cover rounded-lg border border-gray-200 cursor-pointer hover:opacity-80 transition-opacity"
                        onClick={() => setImageModal({ url: selected.selfie_with_id_url!, alt: "Selfie avec pièce d'identité" })}
                      />
                    ) : (
                      <div className="w-full h-48 bg-gray-100 rounded-lg flex items-center justify-center text-gray-400">
                        Non fourni
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex gap-3">
                  <button
                    onClick={() => handleVerify(selected.id, true)}
                    disabled={actionLoading === selected.id}
                    className="flex-1 bg-green-600 hover:bg-green-700 text-white font-semibold py-3 rounded-lg transition-colors disabled:opacity-60"
                  >
                    {actionLoading === selected.id ? "..." : "Approuver"}
                  </button>
                  <button
                    onClick={() => handleVerify(selected.id, false)}
                    disabled={actionLoading === selected.id}
                    className="flex-1 bg-red-600 hover:bg-red-700 text-white font-semibold py-3 rounded-lg transition-colors disabled:opacity-60"
                  >
                    {actionLoading === selected.id ? "..." : "Rejeter"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-gray-100 p-12 text-center">
                <p className="text-gray-400">Sélectionnez un mécanicien pour voir les détails</p>
              </div>
            )}
          </div>
        </div>
      )}

      {imageModal && (
        <ImageModal url={imageModal.url} alt={imageModal.alt} onClose={() => setImageModal(null)} />
      )}
    </div>
  );
}
