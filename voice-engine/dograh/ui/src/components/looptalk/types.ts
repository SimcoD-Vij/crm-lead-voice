export interface TestSession {
    id: number;
    name: string;
    description?: string;
    test_type: string;
    status: string;
    actor_workflow_name: string;
    adversary_workflow_name: string;
    created_at: string;
    updated_at: string;
    test_metadata?: {
        concurrent_pairs?: number;
        [key: string]: unknown;
    };
}

export interface Conversation {
    id: number;
    test_session_id: number;
    conversation_pair_id?: string;
    status: string;
    created_at: string;
    updated_at: string;
}
