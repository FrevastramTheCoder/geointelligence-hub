/**
 * Analysis Module Index
 * All spatial analyses now use the GEE REST API (no ee package needed in browser).
 */
export {
  computeNDVI,
  computeNDWI,
  computeNDBI,
  computeElevation,
  computeSlope,
  getSentinel2RGB,
  runVegetationAnalysis,
  runChangeDetection,
} from '../services/imageryService';

export { runUrbanGrowth } from './urbanGrowth';
export { runBufferAnalysis } from './buffer';
export { runIntersectionAnalysis } from './intersection';
export { runProximityAnalysis } from './proximity';
export { computeArea } from './area';
export { computeDistance } from './distance';
