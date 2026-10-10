import { Box, CircularProgress } from '@mui/material';
import { WelcomePage } from './pages/WelcomePage';
import { SetupWizard } from './pages/SetupWizard';
import { MainLayout } from './components/layout/MainLayout';
import { useApp } from './context/AppContext';

export default function App() {
  const { page, handleWizardComplete, handleLoginComplete } = useApp();

  if (page === 'loading') {
    return (
      <Box sx={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (page === 'welcome') return <WelcomePage onComplete={handleLoginComplete} />;
  if (page === 'wizard') return <SetupWizard onComplete={handleWizardComplete} />;
  return <MainLayout />;
}
