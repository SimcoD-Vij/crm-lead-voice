'use client';

import Nango from '@nangohq/frontend';
import { useState } from 'react';

import { createSessionApiV1IntegrationSessionPost } from "@/client/sdk.gen";
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';


export default function CreateIntegrationButton() {
    const [isLoading, setIsLoading] = useState(false);
    const { user, getAccessToken } = useAuth();

    const handleCreateIntegration = async () => {
        setIsLoading(true);
        try {
            if (!user) {
                throw new Error('User not authenticated');
            }
            const accessToken = await getAccessToken();

            // Fetch session details from our API
            const sessionResponse = await createSessionApiV1IntegrationSessionPost({
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });

            if (!sessionResponse.data?.session_token) {
                throw new Error('Failed to get session token');
            }

            // Initialize Nango and open connect UI
            const nango = new Nango();
            const connect = nango.openConnectUI({
                onEvent: (event) => {
                    if (event.type === 'close') {
                        // Handle modal closed
                        setIsLoading(false);
                        logger.info('Nango connect UI closed');
                    } else if (event.type === 'connect') {
                        // Handle auth flow successful
                        setIsLoading(false);
                        logger.info('Integration connected successfully');
                        // Refresh the page to show new integrations
                        window.location.reload();
                    }
                },
            });

            // Set the session token to initialize the connect UI
            connect.setSessionToken(sessionResponse.data.session_token);

        } catch (err) {
            logger.error(`Error creating integration: ${err}`);
            setIsLoading(false);
            // You might want to show a toast notification here
            alert('Failed to create integration. Please try again.');
        }
    };

    return (
        <Button onClick={handleCreateIntegration} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Create Integration'}
        </Button>
    );
}
