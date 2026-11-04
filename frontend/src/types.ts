export type Role = "COMPANY_ADMIN" | "AGENCY_MANAGER" | "TICKET_AGENT" | "BOARDING_AGENT" | "DRIVER";

export interface Me {
  id: number;
  email: string;
  full_name: string;
  is_platform_admin: boolean;
  role: Role | null;
  agency_id: number | null;
  permissions: string[];
  tenant: { id: number; name: string; slug: string; currency: string; timezone: string; status: string; settings: Record<string, unknown> } | null;
}

export interface Agency { id: number; name: string; city: string; address: string; phone: string; is_active: boolean }
export interface Bus { id: number; plate: string; brand: string; model: string; capacity: number; status: string; seat_count: number }
export interface Driver { id: number; full_name: string; phone: string; license_number: string; is_active: boolean }
export interface Trip {
  id: number; reference: string; agency: number; agency_name: string; origin: string; destination: string;
  departure_at: string; arrival_estimated_at: string | null; bus: number; bus_plate: string; capacity: number;
  price: string; currency: string; status: TripStatus; status_label: string; notes: string; sold: number;
  drivers_detail: { id: number; full_name: string }[];
}
export type TripStatus = "DRAFT" | "OPEN" | "BOARDING" | "CLOSED" | "COMPLETED" | "CANCELLED" | "SUSPENDED";
export interface Ticket {
  id: number; reference: string; trip: number; trip_reference: string; route: string; passenger_name: string;
  passenger_phone: string; seat: number | null; seat_code: string | null; price: string; currency: string;
  status: "ACTIVE" | "CANCELLED"; status_label: string; boarded: boolean; payment_method: string | null; created_at: string;
}
export interface SeatInfo { capacity: number; sold: number; remaining: number; seat_selection: boolean; seats: { id: number; code: string; available: boolean }[] }
export interface ScanOutcome {
  result: "VALIDATED" | "ALREADY_BOARDED" | "INVALID" | "CANCELLED" | "WRONG_TRIP" | "TRIP_CLOSED" | "NOT_ELIGIBLE";
  color: "green" | "red" | "orange";
  message: string;
  replay: boolean;
  ticket?: { reference: string; passenger: string; seat: string | null };
}
export interface ManifestRow { id: number; type: "PREVIEW" | "FINAL"; type_label: string; number: string; version: number; status: string; status_label: string; created_by_name: string | null; created_at: string }
export interface Tenant { id: number; name: string; slug: string; status: string; currency: string; timezone: string; plan_name: string | null; contact_email: string; counts: { agencies: number; users: number } }
export interface Plan { id: number; name: string; price: string; currency: string; max_agencies: number; max_users: number; max_trips_per_month: number; max_tickets_per_month: number }
