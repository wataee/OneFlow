export type UserRole = 'admin' | 'user';

export type TaskType = 
  | 'DOCUMENT_PROCESSING'
  | 'NOMENCLATURE_MATCHING'
  | 'BANK_OPERATION'
  | 'WAREHOUSE_RECONCILIATION';

export type TaskStatus = 
  | 'PENDING'
  | 'PROCESSING'
  | 'REVIEW'
  | 'COMPLETED'
  | 'FAILED';

export type ReviewStatus = 'PENDING' | 'RESOLVED';
export type ReviewDecision = 'approve' | 'reject' | 'edit';

export interface User {
  id: string;
  organization_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface Organization {
  id: string;
  name: string;
  created_at: string;
}

export interface Task {
  id: string;
  organization_id: string;
  type: TaskType;
  status: TaskStatus;
  input_data: Record<string, any>;
  output_data?: Record<string, any> | null;
  error?: string | null;
  confidence?: number | null;
  retry_count: number;
  created_at: string;
  updated_at: string;
}

export interface ReviewTask {
  id: string;
  organization_id: string;
  task_id: string;
  status: ReviewStatus;
  ai_result: Record<string, any>;
  proposed_changes?: Record<string, any> | null;
  user_decision?: ReviewDecision | null;
  rejection_reason?: string | null;
  decided_by?: string | null;
  created_at: string;
  resolved_at?: string | null;
}

export interface FileMetadata {
  id: string;
  organization_id: string;
  task_id?: string | null;
  filename: string;
  stored_path: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
  deleted_at?: string | null;
}

export interface DashboardMetrics {
  total_tasks: number;
  pending: number;
  processing: number;
  in_review: number;
  completed: number;
  failed: number;
  automated_without_human: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
