window.config = {
  routerBasename: '/',
  extensions: [],
  modes: [],
  showStudyList: true,

  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'dicomweb',
      configuration: {
        friendlyName: 'OTTAVA · Orthanc PACS',
        name: 'OTTAVA_ORTHANC',

        wadoUriRoot: '/wado',
        qidoRoot: '/dicom-web',
        wadoRoot: '/dicom-web',

        qidoSupportsIncludeField: false,
        supportsReject: false,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
        omitQuotationForMultipartRequest: true
      }
    }
  ],

  defaultDataSourceName: 'dicomweb'
};
