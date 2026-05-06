'use client';

import { format } from 'date-fns';
import { Eye, Pause, Play, Users } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

import { TestSession } from './types';

interface TestSessionCardProps {
    session: TestSession;
}

export function TestSessionCard({ session }: TestSessionCardProps) {
    const router = useRouter();

    const handleViewDetails = () => {
        router.push(`/looptalk/${session.id}`);
    };

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

    const getTestTypeIcon = (type: string) => {
        switch (type) {
            case 'load_test':
                return <Users className="h-4 w-4" />;
            default:
                return <Play className="h-4 w-4" />;
        }
    };

    return (
        <Card className="hover:shadow-lg transition-shadow cursor-pointer" onClick={handleViewDetails}>
            <CardHeader>
                <div className="flex justify-between items-start">
                    <CardTitle className="text-lg">{session.name}</CardTitle>
                    <Badge variant={getStatusBadgeVariant(session.status)}>
                        {session.status}
                    </Badge>
                </div>
                {session.description && (
                    <CardDescription>{session.description}</CardDescription>
                )}
            </CardHeader>
            <CardContent>
                <div className="space-y-2">
                    <div className="flex items-center gap-2 text-sm text-gray-600">
                        {getTestTypeIcon(session.test_type)}
                        <span className="capitalize">{session.test_type.replace('_', ' ')}</span>
                    </div>
                    <div className="text-sm text-gray-500">
                        Created: {format(new Date(session.created_at), 'MMM d, yyyy h:mm a')}
                    </div>
                    {session.test_metadata?.concurrent_pairs && (
                        <div className="text-sm text-gray-600">
                            Concurrent pairs: {session.test_metadata.concurrent_pairs}
                        </div>
                    )}
                </div>
                <div className="mt-4 flex gap-2">
                    {session.status === 'active' && (
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={(e) => {
                                e.stopPropagation();
                                // TODO: Implement pause functionality
                            }}
                        >
                            <Pause className="h-4 w-4 mr-1" />
                            Pause
                        </Button>
                    )}
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={(e) => {
                            e.stopPropagation();
                            handleViewDetails();
                        }}
                    >
                        <Eye className="h-4 w-4 mr-1" />
                        View
                    </Button>
                </div>
            </CardContent>
        </Card>
    );
}
