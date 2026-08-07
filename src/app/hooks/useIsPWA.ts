import { useState, useEffect } from 'react';

export function useIsPWA() {
  const [isPWA, setIsPWA] = useState(false);

  useEffect(() => {
    const checkPWA = window.matchMedia('(display-mode: standalone)').matches 
                  || (window.navigator as any).standalone === true;
    setIsPWA(checkPWA);
  }, []);

  return isPWA;
}
