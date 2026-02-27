import { useEffect, useState } from "react";
import api from "../api/client";
import type { User } from "../types";

const ROLE_TABS = [
  { value: "", label: "Tous" },
  { value: "buyer", label: "Acheteurs" },
  { value: "mechanic", label: "Mécaniciens" },
  { value: "admin", label: "Admins" },
];

const ROLE_LABELS: Record<string, string> = {
  buyer: "Acheteur",
  mechanic: "Mécanicien",
  admin: "Admin",
};

export function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [role, setRole] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 20;

  useEffect(() => {
    setLoading(true);
    const params: Record<string, string | number> = { limit, offset };
    if (role) params.role = role;
    api.get("/admin/users", { params }).then((res) => {
      setUsers(res.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [role, offset]);

  const handleRoleChange = (newRole: string) => {
    setRole(newRole);
    setOffset(0);
  };

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Utilisateurs</h1>

      <div className="flex gap-2 mb-6">
        {ROLE_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => handleRoleChange(tab.value)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              role === tab.value
                ? "bg-gray-900 text-white"
                : "bg-white text-gray-600 border border-gray-200 hover:bg-gray-50"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Nom</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Email</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Rôle</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Vérifié</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">Inscription</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-gray-500">Chargement...</td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-gray-500">Aucun utilisateur</td>
              </tr>
            ) : (
              users.map((user) => (
                <tr key={user.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 text-sm font-medium text-gray-900">
                    {user.first_name || ""} {user.last_name || ""}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">{user.email}</td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      user.role === "admin" ? "bg-purple-100 text-purple-800" :
                      user.role === "mechanic" ? "bg-blue-100 text-blue-800" :
                      "bg-green-100 text-green-800"
                    }`}>
                      {ROLE_LABELS[user.role] || user.role}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    {user.is_verified ? (
                      <span className="text-green-600 text-sm">Oui</span>
                    ) : (
                      <span className="text-gray-400 text-sm">Non</span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {new Date(user.created_at).toLocaleDateString("fr-FR")}
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
        <span className="text-sm text-gray-500">
          Page {Math.floor(offset / limit) + 1}
        </span>
        <button
          onClick={() => setOffset(offset + limit)}
          disabled={users.length < limit}
          className="px-4 py-2 text-sm font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
        >
          Suivant
        </button>
      </div>
    </div>
  );
}
