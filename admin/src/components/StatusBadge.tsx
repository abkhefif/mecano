const STATUS_COLORS: Record<string, string> = {
  pending_acceptance: "bg-yellow-100 text-yellow-800",
  confirmed: "bg-blue-100 text-blue-800",
  check_in_done: "bg-indigo-100 text-indigo-800",
  check_out_done: "bg-purple-100 text-purple-800",
  validated: "bg-green-100 text-green-800",
  completed: "bg-green-100 text-green-800",
  cancelled: "bg-red-100 text-red-800",
  disputed: "bg-orange-100 text-orange-800",
  open: "bg-yellow-100 text-yellow-800",
  closed: "bg-gray-100 text-gray-800",
  resolved_buyer: "bg-green-100 text-green-800",
  resolved_mechanic: "bg-green-100 text-green-800",
};

const STATUS_LABELS: Record<string, string> = {
  pending_acceptance: "En attente",
  confirmed: "Confirmée",
  awaiting_mechanic_code: "Code attendu",
  check_in_done: "Check-in fait",
  check_out_done: "Check-out fait",
  validated: "Validée",
  completed: "Terminée",
  cancelled: "Annulée",
  disputed: "Litige",
  open: "Ouvert",
  closed: "Fermé",
  resolved_buyer: "Résolu (acheteur)",
  resolved_mechanic: "Résolu (mécanicien)",
};

export function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] || "bg-gray-100 text-gray-800";
  const label = STATUS_LABELS[status] || status;

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${color}`}>
      {label}
    </span>
  );
}
