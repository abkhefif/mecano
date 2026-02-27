export interface Stats {
  total_users: number;
  total_mechanics: number;
  total_buyers: number;
  total_bookings: number;
  total_revenue: number;
  pending_verifications: number;
  active_disputes: number;
}

export interface MechanicProfile {
  id: string;
  city: string;
  is_identity_verified: boolean;
  is_active: boolean;
  identity_document_url: string | null;
  selfie_with_id_url: string | null;
  rating_avg: number;
  total_reviews: number;
  suspended_until: string | null;
}

export interface User {
  id: string;
  email: string;
  role: "buyer" | "mechanic" | "admin";
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  is_verified: boolean;
  created_at: string;
  mechanic_profile: MechanicProfile | null;
}

export interface PendingMechanic {
  id: string;
  user_id: string;
  city: string;
  identity_document_url: string | null;
  selfie_with_id_url: string | null;
  is_identity_verified: boolean;
  email: string;
  first_name: string | null;
  last_name: string | null;
  created_at: string;
}

export interface Booking {
  id: string;
  buyer_id: string;
  mechanic_id: string;
  status: string;
  vehicle_type: string;
  vehicle_brand: string;
  vehicle_model: string;
  vehicle_year: number;
  total_price: string | null;
  commission_amount: string | null;
  created_at: string;
}

export interface RevenueEntry {
  date: string;
  revenue: number;
  commission: number;
}
