'use client';

import { format } from 'date-fns';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

import { TestSession } from './types';

interface TestSessionDetailsProps {
    session: TestSession;
}

export function TestSessionDetails({ session }: TestSessionDetailsProps) {
    const getStatusBadgeVariant = (status: string) => {
        switch (status) {
            case 'active':
                return 'default';
            case 'completed':
                return 'secondary';
            case 'failed':
                return 'destructive';
            default:
                return 'outline';
        }
    };

    return (
        <Card>
            <CardHeader>
                <div className="flex justify-between items-start">
                    <div>
                        <CardTitle className="text-2xl">{session.name}</CardTitle>
                        {session.description && (
                            <CardDescription className="mt-2">{session.description}</CardDescription>
                        )}
                    </div>
                    <Badge variant={getStatusBadgeVariant(session.status)} className="text-lg px-3 py-1">
                        {session.status}
                    </Badge>
                </div>
            </CardHeader>
            <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <h3 className="font-semibold text-sm text-gray-600 mb-1">Test Type</h3>
                        <p className="capitalize">{session.test_type.replace('_', ' ')}</p>
                    </div>
                    <div>
                        <h3 className="font-semibold text-sm text-gray-600 mb-1">Created</h3>
                        <p>{format(new Date(session.created_at), 'MMM d, yyyy h:mm a')}</p>
                    </div>
                    <div>
                        <h3 className="font-semibold text-sm text-gray-600 mb-1">Actor Workflow</h3>
                        <p>{session.actor_workflow_name}</p>
                    </div>
                    <div>
                        <h3 className="font-semibold text-sm text-gray-600 mb-1">Adversary Workflow</h3>
                        <p>{session.adversary_workflow_name}</p>
                    </div>
                    {session.test_metadata?.concurrent_pairs && (
                        <div>
                            <h3 className="font-semibold text-sm text-gray-600 mb-1">Concurrent Pairs</h3>
                            <p>{session.test_metadata.concurrent_pairs}</p>
                        </div>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}
