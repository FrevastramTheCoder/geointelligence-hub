import { getSentinel2 } from '../services/imageryService';

const LC_NAMES = { 0: 'Built-up', 1: 'Vegetation', 2: 'Bare Soil', 3: 'Water' };

export async function runLandCoverClassification(geometry, startDate, endDate) {
  const ee = window.ee;
  const s2 = getSentinel2(geometry, startDate, endDate);
  const ndvi = s2.normalizedDifference(['B8', 'B4']).rename('NDVI');
  const ndbi = s2.normalizedDifference(['B11', 'B8']).rename('NDBI');
  const mndwi = s2.normalizedDifference(['B3', 'B11']).rename('MNDWI');
  const img = s2.addBands(ndvi).addBands(ndbi).addBands(mndwi);

  const wc = ee.Image('ESA/WorldCover/v200/2021').select('Map').clip(geometry);
  const lcR = wc.remap(
    [10,20,30,40,50,60,70,80,90,95,100],
    [1,1,1,1,0,2,2,3,1,1,1], 0
  ).rename('landcover');

  const pts = lcR.stratifiedSample({ numPoints: 80, classBand: 'landcover', region: geometry, scale: 10, seed: 42, geometries: true });

  const bands = ['B2','B3','B4','B5','B6','B7','B8','B8A','B11','B12','NDVI','NDBI','MNDWI'];
  const training = img.select(bands).sampleRegions({ collection: pts, properties: ['landcover'], scale: 10 });
  const sample = training.randomColumn('random', 42);
  const train = sample.filter(ee.Filter.lt('random', 0.7));
  const validate = sample.filter(ee.Filter.gte('random', 0.7));

  const clf = ee.Classifier.smileRandomForest(150).train({ features: train, classProperty: 'landcover', inputProperties: bands });
  const classified = img.select(bands).classify(clf).focalMode(2, 'circle', 'pixels', 2);

  const va = validate.classify(clf);
  const cm = va.errorMatrix('landcover', 'classification');
  const oa = cm.accuracy();
  const ka = cm.kappa();

  const areaImg = ee.Image.pixelArea().addBands(classified);
  const areaStats = areaImg.reduceRegion({
    reducer: ee.Reducer.sum().group({ groupField: 1, groupName: 'class' }),
    geometry: geometry, scale: 10, maxPixels: 1e9,
  });

  const [oaVal, kaVal, areaRaw] = await Promise.all([
    new Promise(r => oa.evaluate(v => r(v))),
    new Promise(r => ka.evaluate(v => r(v))),
    new Promise(r => areaStats.evaluate(v => r(v))),
  ]);

  const url = classified.getThumbURL({
    min: 0, max: 3, palette: ['#FF0000','#00FF00','#FFD700','#0000FF'],
    region: geometry, dimensions: '800',
  });

  const areas = {};
  if (areaRaw?.groups) {
    areaRaw.groups.forEach(g => { areas[LC_NAMES[g.class] || g.class] = (g.sum / 10000).toFixed(1) + ' ha'; });
  }

  return {
    type: 'LandCover', label: 'Land Cover Classification',
    stats: { accuracy: `${(oaVal*100).toFixed(1)}%`, kappa: kaVal.toFixed(4), ...areas },
    imageUrl: url,
    interpretation: `Random Forest classified ${Object.keys(LC_NAMES).length} classes with ${(oaVal*100).toFixed(0)}% accuracy.`,
    colorPalette: 'red-green-yellow-blue',
  };
}
