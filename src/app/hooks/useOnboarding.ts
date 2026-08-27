import { useState, useCallback } from 'react';

const ONBOARDING_KEY = 'truerating_onboarding_seen';
const RESULTS_GUIDE_KEY = 'truerating_results_guide_seen';

export function useOnboarding() {
  const [isOpen, setIsOpen] = useState<boolean>(() => {
    try {
      return !localStorage.getItem(ONBOARDING_KEY);
    } catch {
      return false;
    }
  });

  const showOnboarding = useCallback(() => {
    setIsOpen(true);
  }, []);

  const dismissOnboarding = useCallback(() => {
    try {
      localStorage.setItem(ONBOARDING_KEY, 'true');
    } catch {
      // ignore
    }
    setIsOpen(false);
  }, []);

  const resetOnboarding = useCallback(() => {
    try {
      localStorage.removeItem(ONBOARDING_KEY);
    } catch {
      // ignore
    }
    setIsOpen(true);
  }, []);

  return {
    isOpen,
    showOnboarding,
    dismissOnboarding,
    resetOnboarding,
  };
}

export function useResultsGuide() {
  const [isOpen, setIsOpen] = useState<boolean>(() => {
    try {
      return !localStorage.getItem(RESULTS_GUIDE_KEY);
    } catch {
      return false;
    }
  });

  const dismissResultsGuide = useCallback(() => {
    try {
      localStorage.setItem(RESULTS_GUIDE_KEY, 'true');
    } catch {
      // ignore
    }
    setIsOpen(false);
  }, []);

  const resetResultsGuide = useCallback(() => {
    try {
      localStorage.removeItem(RESULTS_GUIDE_KEY);
    } catch {
      // ignore
    }
    setIsOpen(true);
  }, []);

  return {
    isOpen,
    dismissResultsGuide,
    resetResultsGuide,
  };
}
