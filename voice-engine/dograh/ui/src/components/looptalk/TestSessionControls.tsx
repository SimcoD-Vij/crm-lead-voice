'use client';

import { Play, RotateCcw, Square } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import {
    startTestSessionApiV1LooptalkTestSessionsTestSessionIdStartPost,
    stopTestSessionApiV1LooptalkTestSessionsTestSessionIdStopPost
} from '@/client/sdk.gen';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';

interface TestSessionControlsProps {
    session: {
        id: number;
        status: string;
        test_type: string;
    };
}

export function TestSessionControls({ session }: TestSessionControlsProps) {
    const router = useRouter();
    const [loading, setLoading] = useState(false);
    const { user, getAccessToken } = useAuth();

    const handleStart = async () => {
        if (!user) return;
        setLoading(true);
        try {
            const accessToken = await getAccessToken();
            await startTestSessionApiV1LooptalkTestSessionsTestSessionIdStartPost({
                path: {
                    test_session_id: session.id
                },
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });
            toast.success('Test session started');
            router.refresh();
        } catch (error) {
            logger.error('Error starting test session:', error);
            toast.error('Failed to start test session');
        } finally {
            setLoading(false);
        }
    };

    const handleStop = async () => {
        if (!user) return;
        setLoading(true);
        try {
            const accessToken = await getAccessToken();
            await stopTestSessionApiV1LooptalkTestSessionsTestSessionIdStopPost({
                path: {
                    test_session_id: session.id
                },
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });
            toast.success('Test session stopped');
            router.refresh();
        } catch (error) {
            logger.error('Error stopping test session:', error);
            toast.error('Failed to stop test session');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Card className="mt-4">
            <CardContent className="pt-6">
                <div className="flex gap-2">
                    {session.status === 'pending' && (
                        <Button
                            onClick={handleStart}
                            disabled={loading}
                            className="flex items-center gap-2"
                        >
                            <Play className="h-4 w-4" />
                            Start Test
                        </Button>
                    )}

                    {session.status === 'active' && (
                        <>
                            <Button
                                variant="destructive"
                                onClick={handleStop}
                                disabled={loading}
                                className="flex items-center gap-2"
                            >
                                <Square className="h-4 w-4" />
                                Stop Test
                            </Button>
                        </>
                    )}

                    {session.status === 'completed' && (
                        <Button
                            variant="outline"
                            onClick={handleStart}
                            disabled={loading}
                            className="flex items-center gap-2"
                        >
                            <RotateCcw className="h-4 w-4" />
                            Restart Test
                        </Button>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}
